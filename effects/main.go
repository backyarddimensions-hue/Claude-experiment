// effects: infers effect tags for every function in a Go module and emits graph.json.
//
// Vocabulary (fixed by the experiment design):
//
//	pure | reads <noun> | writes <noun> | net | fs | mut
//
// A function with no inferred effect is only called "pure" if the tool can prove it:
// no global writes, no mutation of caller-visible state, no nondeterminism, no logging,
// no unresolved dynamic calls, no unclassified external calls. Otherwise it is reported as
// "unclassified" with the reasons, and left for hand-tagging.
//
// Usage: effects -dir <module root> -out graph.json
package main

import (
	"encoding/json"
	"flag"
	"fmt"
	"go/ast"
	"go/token"
	"go/types"
	"os"
	"path/filepath"
	"sort"
	"strings"

	"golang.org/x/tools/go/callgraph/cha"
	"golang.org/x/tools/go/callgraph/vta"
	"golang.org/x/tools/go/packages"
	"golang.org/x/tools/go/ssa"
	"golang.org/x/tools/go/ssa/ssautil"
)

type Evidence struct {
	Effect string `json:"effect"`
	Sink   string `json:"sink"`
	Pos    string `json:"pos"`
	Approx bool   `json:"approx,omitempty"` // noun recovered by fallback, not from a constant SQL string
}

type Func struct {
	ID        string     `json:"id"`
	Pkg       string     `json:"pkg"`
	TopDir    string     `json:"top_dir"`
	Name      string     `json:"name"`
	Recv      string     `json:"recv,omitempty"`
	File      string     `json:"file"`
	Line      int        `json:"line"`
	Signature string     `json:"signature"`
	Exported  bool       `json:"exported"`
	Declared  []string   `json:"declared"`                  // parsed from the @effects tag in source; null if untagged
	Inferred  []string   `json:"inferred"`                  // transitive effects in the tag vocabulary (incl. mut)
	InfApprox []string   `json:"inferred_approx,omitempty"` // subset of inferred whose noun was guessed, not proven, on every path
	Mut       bool       `json:"mut"`                       // mutates state reachable from its receiver or arguments
	MutWhy    string     `json:"mut_example,omitempty"`
	Ambient   []string   `json:"ambient,omitempty"` // logging, nondeterministic, concurrency, http-server-io, stream-io: reported, never tagged
	Direct    []Evidence `json:"direct,omitempty"`
	Pure      bool       `json:"pure"`
	Impure    []string   `json:"impure_reasons,omitempty"` // non-ambient reasons the vocabulary cannot express (transitive)
	ImpureEx  []string   `json:"impure_examples,omitempty"`
	Callees   []string   `json:"callees"`
	Callers   []string   `json:"callers"`
	Refs      []string   `json:"referenced_by,omitempty"` // functions that take this one as a value (e.g. route registration)
	Unres     []string   `json:"unresolved,omitempty"`

	fn      *ssa.Function
	eff     map[string]bool
	exact   map[string]bool   // effect has at least one fully proven derivation
	cats    map[string]string // impurity category -> example
	mutPar  bool              // mutates state reachable from its own params/receiver
	mutEx   string
	calls   []callSite
	sqlPar  map[int]string // parameter index -> sql method name: this function forwards that param as SQL text
	callees map[*Func]bool
	callers map[*Func]bool
	refs    map[*Func]bool
}

type callSite struct {
	callee *Func
	args   []ssa.Value
	in     ssa.Instruction
	done   map[int]bool
}

var (
	prog    *ssa.Program
	modPath string
	modDir  string
	funcs   = map[*ssa.Function]*Func{}
	tables  = map[string]bool{}
	mutGlob = map[*ssa.Global]bool{}
	recvStr = map[string][]string{} // receiver type -> all SQL-like string constants in its methods
)

func main() {
	dir := flag.String("dir", ".", "module root")
	out := flag.String("out", "graph.json", "output file")
	flag.Parse()
	abs, _ := filepath.Abs(*dir)
	modDir = abs

	cfg := &packages.Config{Mode: packages.LoadAllSyntax | packages.NeedModule, Dir: abs, Tests: false}
	pkgs, err := packages.Load(cfg, "./...")
	if err != nil {
		fatal(err)
	}
	if packages.PrintErrors(pkgs) > 0 {
		fatal(fmt.Errorf("package load errors"))
	}
	for _, p := range pkgs {
		if p.Module != nil && p.Module.Main {
			modPath = p.Module.Path
			break
		}
	}
	var spkgs []*ssa.Package
	prog, spkgs = ssautil.AllPackages(pkgs, ssa.InstantiateGenerics)
	_ = spkgs
	prog.Build()

	all := ssautil.AllFunctions(prog)
	cg := vta.CallGraph(all, cha.CallGraph(prog))
	siteCallees := map[ssa.CallInstruction][]*ssa.Function{}
	for _, n := range cg.Nodes {
		for _, e := range n.Out {
			if e.Site != nil {
				siteCallees[e.Site] = append(siteCallees[e.Site], e.Callee.Func)
			}
		}
	}

	// Register module functions that have source.
	for fn := range all {
		if !inModule(fn) || fn.Blocks == nil {
			continue
		}
		if fn.Synthetic != "" && fn.Synthetic != "package initializer" {
			continue
		}
		register(fn)
	}
	// Pre-passes: table names, mutable globals, per-receiver SQL strings.
	for fn := range funcs {
		scanConsts(fn)
	}
	for fn, f := range funcs {
		isInit := fn.Name() == "init" || strings.HasPrefix(fn.Name(), "init#")
		for _, b := range fn.Blocks {
			for _, in := range b.Instrs {
				if st, ok := in.(*ssa.Store); ok && !isInit {
					if g, kind := base(st.Addr); kind == "global" {
						mutGlob[g.(*ssa.Global)] = true
					}
				}
			}
		}
		_ = f
	}
	for fn, f := range funcs {
		analyze(fn, f, siteCallees)
	}
	forwardSQL()
	orphanSQL()
	propagate()
	emit(*out)
}

func fatal(err error) { fmt.Fprintln(os.Stderr, "effects:", err); os.Exit(1) }

// ---------- identity ----------

func pkgOf(fn *ssa.Function) *types.Package {
	for f := fn; f != nil; f = f.Parent() {
		if o := f.Origin(); o != nil {
			f = o
		}
		if f.Pkg != nil {
			return f.Pkg.Pkg
		}
		if f.Object() != nil && f.Object().Pkg() != nil {
			return f.Object().Pkg()
		}
	}
	return nil
}

func inModule(fn *ssa.Function) bool {
	p := pkgOf(fn)
	return p != nil && (p.Path() == modPath || strings.HasPrefix(p.Path(), modPath+"/"))
}

// canon maps wrappers, bound-method closures and generic instances to the declared function.
func canon(fn *ssa.Function) *ssa.Function {
	if fn == nil {
		return nil
	}
	if o := fn.Origin(); o != nil {
		fn = o
	}
	if fn.Synthetic != "" && fn.Synthetic != "package initializer" {
		if obj, ok := fn.Object().(*types.Func); ok {
			if d := prog.FuncValue(obj); d != nil {
				if o := d.Origin(); o != nil {
					d = o
				}
				return d
			}
		}
	}
	return fn
}

func lookup(fn *ssa.Function) *Func { return funcs[canon(fn)] }

func relPkg(p string) string {
	if p == modPath {
		return "."
	}
	return strings.TrimPrefix(p, modPath+"/")
}

func register(fn *ssa.Function) {
	p := pkgOf(fn)
	f := &Func{fn: fn, Pkg: relPkg(p.Path()), eff: map[string]bool{}, exact: map[string]bool{}, cats: map[string]string{},
		callees: map[*Func]bool{}, callers: map[*Func]bool{}, refs: map[*Func]bool{}}
	parts := strings.Split(f.Pkg, "/")
	f.TopDir = parts[0]
	if parts[0] == "internal" && len(parts) > 1 {
		f.TopDir = "internal/" + parts[1]
	}
	name := fn.Name()
	recv := ""
	root := fn
	for root.Parent() != nil {
		root = root.Parent()
	}
	if sig := root.Signature; sig.Recv() != nil {
		recv = types.TypeString(sig.Recv().Type(), func(*types.Package) string { return "" })
	}
	if fn.Parent() != nil { // anonymous: name is like "Outer$1"
		f.Exported = false
	} else {
		f.Exported = token.IsExported(name)
	}
	f.Name, f.Recv = name, recv
	if recv != "" {
		f.ID = f.Pkg + ".(" + recv + ")." + name
	} else {
		f.ID = f.Pkg + "." + name
	}
	pos := prog.Fset.Position(fn.Pos())
	if fn.Synthetic == "package initializer" {
		f.Exported = false
	}
	if pos.IsValid() {
		f.File, _ = filepath.Rel(modDir, pos.Filename)
		f.Line = pos.Line
	}
	f.Signature = signature(fn)
	if decl, ok := fn.Syntax().(*ast.FuncDecl); ok && decl.Doc != nil {
		for _, c := range decl.Doc.List {
			if i := strings.Index(c.Text, "@effects:"); i >= 0 {
				f.Declared = []string{}
				for _, t := range strings.Split(c.Text[i+len("@effects:"):], ",") {
					if t = strings.TrimSpace(t); t != "" {
						f.Declared = append(f.Declared, t)
					}
				}
			}
		}
	}
	funcs[fn] = f
}

func signature(fn *ssa.Function) string {
	q := func(p *types.Package) string {
		if p.Path() == modPath || strings.HasPrefix(p.Path(), modPath+"/") {
			return p.Name()
		}
		return p.Name()
	}
	sig := fn.Signature
	s := "func "
	if sig.Recv() != nil {
		s += "(" + types.TypeString(sig.Recv().Type(), q) + ") "
	}
	s += fn.Name() + strings.TrimPrefix(types.TypeString(sig, q), "func")
	return s
}

func pos(in ssa.Instruction) string {
	p := prog.Fset.Position(in.Pos())
	if !p.IsValid() {
		return ""
	}
	r, _ := filepath.Rel(modDir, p.Filename)
	return fmt.Sprintf("%s:%d", r, p.Line)
}

// ---------- SQL ----------

func scanConsts(fn *ssa.Function) {
	recv := ""
	if fn.Signature.Recv() != nil {
		recv = fn.Signature.Recv().Type().String()
	}
	for _, s := range funcConsts(fn) {
		for _, t := range createdTables(s) {
			tables[t] = true
		}
		if recv != "" && sqlLike(s) {
			recvStr[recv] = append(recvStr[recv], s)
		}
	}
}

func funcConsts(fn *ssa.Function) []string {
	var out []string
	seen := map[string]bool{}
	for _, b := range fn.Blocks {
		for _, in := range b.Instrs {
			for _, op := range in.Operands(nil) {
				if c, ok := (*op).(*ssa.Const); ok && c.Value != nil && isString(c.Type()) {
					s := constString(c)
					if !seen[s] {
						seen[s] = true
						out = append(out, s)
					}
				}
			}
		}
	}
	return out
}

func isString(t types.Type) bool {
	b, ok := t.Underlying().(*types.Basic)
	return ok && b.Info()&types.IsString != 0
}

// resolveSQL returns the constant fragments a query value is built from; ok=false if none found.
func resolveSQL(v ssa.Value, depth int, seen map[ssa.Value]bool) ([]string, bool) {
	if depth > 8 || seen[v] {
		return nil, false
	}
	seen[v] = true
	switch x := v.(type) {
	case *ssa.Const:
		if x.Value != nil && isString(x.Type()) {
			return []string{constString(x)}, true
		}
	case *ssa.Phi:
		var out []string
		any := false
		for _, e := range x.Edges {
			if s, ok := resolveSQL(e, depth+1, seen); ok {
				out, any = append(out, s...), true
			}
		}
		return out, any
	case *ssa.BinOp:
		if x.Op == token.ADD {
			a, okA := resolveSQL(x.X, depth+1, seen)
			b, okB := resolveSQL(x.Y, depth+1, seen)
			if okA || okB {
				return []string{strings.Join(a, " ") + " " + strings.Join(b, " ")}, true
			}
		}
	case *ssa.Call:
		if c := x.Call.StaticCallee(); c != nil && c.Pkg != nil && c.Pkg.Pkg.Path() == "fmt" && c.Name() == "Sprintf" && len(x.Call.Args) > 0 {
			out, ok := resolveSQL(x.Call.Args[0], depth+1, seen)
			if !ok {
				return nil, false
			}
			// Substitute constant string arguments for the verbs, in order; unknowns become "?".
			argStr := map[int64]string{}
			if len(x.Call.Args) > 1 {
				if sl, ok2 := x.Call.Args[1].(*ssa.Slice); ok2 {
					if al, ok3 := sl.X.(*ssa.Alloc); ok3 {
						for _, r := range *al.Referrers() {
							ia, ok4 := r.(*ssa.IndexAddr)
							if !ok4 {
								continue
							}
							k, ok5 := ia.Index.(*ssa.Const)
							if !ok5 || k.Value == nil {
								continue
							}
							for _, r2 := range *ia.Referrers() {
								if st, ok6 := r2.(*ssa.Store); ok6 {
									var val ssa.Value = st.Val
									if mi, ok7 := val.(*ssa.MakeInterface); ok7 {
										val = mi.X
									}
									if sv, ok8 := resolveSQL(val, depth+1, seen); ok8 && len(sv) == 1 {
										argStr[k.Int64()] = sv[0]
									}
								}
							}
						}
					}
				}
			}
			for n, format := range out {
				idx := int64(0)
				out[n] = reFmtVerb.ReplaceAllStringFunc(format, func(string) string {
					v, has := argStr[idx]
					idx++
					if has {
						return v
					}
					return "?"
				})
			}
			return out, ok
		}
	case *ssa.UnOp:
		if x.Op == token.MUL {
			if al, ok := x.X.(*ssa.Alloc); ok {
				var out []string
				any := false
				for _, r := range *al.Referrers() {
					if st, ok := r.(*ssa.Store); ok {
						if s, ok := resolveSQL(st.Val, depth+1, seen); ok {
							out, any = append(out, s...), true
						}
					}
				}
				return out, any
			}
		}
	}
	return nil, false
}

// ---------- analysis ----------

func (f *Func) add(effect, sink string, in ssa.Instruction, approx bool) {
	if in == nil {
		return
	}
	f.eff[effect] = true
	if !approx {
		f.exact[effect] = true
	}
	f.Direct = append(f.Direct, Evidence{Effect: effect, Sink: sink, Pos: pos(in), Approx: approx})
}

func (f *Func) cat(c, example string) {
	if _, ok := f.cats[c]; !ok {
		f.cats[c] = example
	}
}

// base traces an address/pointer back to where it came from.
// kinds: "global", "param", "local", "unknown".
func base(v ssa.Value) (ssa.Value, string) { return baseS(v, map[ssa.Value]bool{}) }

func baseS(v ssa.Value, seen map[ssa.Value]bool) (ssa.Value, string) {
	for i := 0; i < 64 && v != nil && !seen[v]; i++ {
		seen[v] = true
		switch x := v.(type) {
		case *ssa.Global:
			return x, "global"
		case *ssa.Parameter:
			return x, "param"
		case *ssa.FreeVar:
			return x, "param"
		case *ssa.Alloc:
			return x, "local"
		case *ssa.MakeMap, *ssa.MakeSlice, *ssa.MakeChan, *ssa.MakeClosure, *ssa.Const:
			return x, "local"
		case *ssa.FieldAddr:
			v = x.X
		case *ssa.IndexAddr:
			v = x.X
		case *ssa.Field:
			v = x.X
		case *ssa.Index:
			v = x.X
		case *ssa.Slice:
			v = x.X
		case *ssa.ChangeType:
			v = x.X
		case *ssa.Convert:
			v = x.X
		case *ssa.MakeInterface:
			v = x.X
		case *ssa.UnOp:
			if x.Op != token.MUL {
				return x, "local"
			}
			// load: a pointer loaded out of a local slot is whatever was stored there
			if al, ok := x.X.(*ssa.Alloc); ok {
				kind := "local"
				var last ssa.Value = al
				for _, r := range *al.Referrers() {
					if st, ok := r.(*ssa.Store); ok && st.Addr == al {
						if bv, k := baseS(st.Val, seen); k != "local" {
							kind, last = k, bv
						}
					}
				}
				return last, kind
			}
			v = x.X
		case *ssa.Phi:
			kind := "local"
			var last ssa.Value = x
			for _, e := range x.Edges {
				if seen[e] {
					continue
				}
				if bv, k := baseS(e, seen); k != "local" {
					kind, last = k, bv
				}
			}
			return last, kind
		default:
			return x, "unknown"
		}
	}
	return v, "unknown"
}

// externalRunner: is this a call into non-module code that may invoke a function argument synchronously?
func externalRunner(c *ssa.CallCommon) bool {
	if c.IsInvoke() {
		n, ok := c.Value.Type().(*types.Named)
		if !ok || n.Obj().Pkg() == nil {
			return false
		}
		p := n.Obj().Pkg().Path()
		return p != modPath && !strings.HasPrefix(p, modPath+"/") && p != "net/http"
	}
	sc := c.StaticCallee()
	if sc == nil || inModule(sc) || pkgOf(sc) == nil {
		return false
	}
	switch pkgOf(sc).Path() {
	case "net/http", "github.com/gin-gonic/gin", "github.com/prometheus/client_golang/prometheus":
		return false // handler registration, not execution
	}
	return true
}

func runByExternal(v ssa.Value, depth int) bool {
	if depth > 3 || v.Referrers() == nil {
		return false
	}
	for _, r := range *v.Referrers() {
		switch x := r.(type) {
		case *ssa.ChangeType:
			if runByExternal(x, depth+1) {
				return true
			}
		case *ssa.MakeInterface:
			if runByExternal(x, depth+1) {
				return true
			}
		case ssa.CallInstruction:
			if x.Common().Value != v && externalRunner(x.Common()) {
				return true
			}
		}
	}
	return false
}

func pointerLike(t types.Type) bool {
	switch t.Underlying().(type) {
	case *types.Pointer, *types.Map, *types.Slice, *types.Chan, *types.Interface, *types.Signature:
		return true
	}
	return false
}

func analyze(fn *ssa.Function, f *Func, siteCallees map[ssa.CallInstruction][]*ssa.Function) {
	noteWrite := func(addr ssa.Value, in ssa.Instruction, what string) {
		b, kind := base(addr)
		switch kind {
		case "global":
			f.cat("writes-global", fmt.Sprintf("%s %s at %s", what, b.Name(), pos(in)))
		case "param":
			f.mutPar = true
			if f.mutEx == "" {
				f.mutEx = fmt.Sprintf("%s via %s at %s", what, b.Name(), pos(in))
			}
		case "unknown":
			f.cat("writes-unknown-pointer", fmt.Sprintf("%s at %s", what, pos(in)))
		}
	}
	for _, b := range fn.Blocks {
		for _, in := range b.Instrs {
			// references to module functions used as values
			for _, op := range in.Operands(nil) {
				if rf, ok := (*op).(*ssa.Function); ok {
					if ci, isCall := in.(ssa.CallInstruction); isCall && ci.Common().Value == rf {
						continue
					}
					if t := lookup(rf); t != nil && t != f {
						// A function value handed straight to external code that runs it (sort.Slice,
						// sync.Once.Do, strings.Map...) is treated as called here. Anything else
						// (stored, returned, registered as a handler) is only a reference; calls made
						// later through module code are found by the call graph.
						run := false
						if v, ok := in.(ssa.Value); ok {
							if _, isMC := in.(*ssa.MakeClosure); isMC {
								run = runByExternal(v, 0)
							} else if _, isConv := in.(*ssa.ChangeType); isConv {
								run = runByExternal(v, 0)
							} else if _, isMI := in.(*ssa.MakeInterface); isMI {
								run = runByExternal(v, 0)
							}
						}
						if ci, ok := in.(ssa.CallInstruction); ok && externalRunner(ci.Common()) {
							run = true
						}
						if run {
							f.calls = append(f.calls, callSite{callee: t})
						} else {
							t.refs[f] = true
						}
					}
				}
			}
			switch x := in.(type) {
			case *ssa.Store:
				noteWrite(x.Addr, in, "store")
			case *ssa.MapUpdate:
				noteWrite(x.Map, in, "map update")
			case *ssa.Send:
				f.cat("concurrency", "channel send at "+pos(in))
			case *ssa.Go:
				f.cat("concurrency", "go statement at "+pos(in))
				call(f, x, siteCallees)
			case *ssa.Select:
				f.cat("concurrency", "select at "+pos(in))
			case *ssa.UnOp:
				if x.Op == token.ARROW {
					f.cat("concurrency", "channel receive at "+pos(in))
				}
				if x.Op == token.MUL {
					if g, ok := x.X.(*ssa.Global); ok && mutGlob[g] {
						f.cat("reads-mutable-global", g.Name()+" at "+pos(in))
					}
				}
			case *ssa.Call:
				call(f, x, siteCallees)
			case *ssa.Defer:
				call(f, x, siteCallees)
			}
		}
	}
}

func call(f *Func, in ssa.CallInstruction, siteCallees map[ssa.CallInstruction][]*ssa.Function) {
	c := in.Common()
	if sc := c.StaticCallee(); sc != nil {
		if t := lookup(sc); t != nil {
			f.calls = append(f.calls, callSite{callee: t, args: c.Args, in: in, done: map[int]bool{}})
			return
		}
		if inModule(sc) {
			return // module function without a body we track (e.g. generic instance already canonicalised)
		}
		external(f, sc, c, in)
		return
	}
	if _, ok := c.Value.(*ssa.Builtin); ok {
		return
	}
	// dynamic call: interface method or function value
	found := false
	for _, callee := range siteCallees[in] {
		if t := lookup(callee); t != nil {
			args := c.Args
			f.calls = append(f.calls, callSite{callee: t, args: args, in: in, done: map[int]bool{}})
			found = true
			continue
		}
		// The call graph resolved this dynamic call to an external sink (e.g. a module-defined
		// interface satisfied by *sql.DB, or an http.RoundTripper).
		if cp := pkgOf(callee); cp != nil && !inModule(callee) {
			rn, nm := recvName(callee), callee.Name()
			isSQL := cp.Path() == "database/sql" && (rn == "DB" || rn == "Tx" || rn == "Conn") &&
				(strings.HasPrefix(nm, "Query") || strings.HasPrefix(nm, "Exec") || strings.HasPrefix(nm, "Prepare"))
			_, isNet := netSink(cp.Path(), rn, nm)
			if isSQL || isNet || fsSink(cp.Path(), rn, nm) && cp.Path() == "os" && rn != "File" {
				cc := *c
				if c.IsInvoke() {
					cc.Args = append([]ssa.Value{c.Value}, c.Args...) // line up with a static method call
				}
				external(f, callee, &cc, in)
				found = true
			}
		}
	}
	if c.IsInvoke() {
		ifacePkg, ifaceName := "", ""
		if n, ok := c.Value.Type().(*types.Named); ok && n.Obj().Pkg() != nil {
			ifacePkg, ifaceName = n.Obj().Pkg().Path(), n.Obj().Name()
		}
		key := ifacePkg + "." + ifaceName + "." + c.Method.Name()
		if e, ok := ifaceSinks[key]; ok {
			f.add(e, key, in, false)
			return
		}
		if c.Method.Name() == "Error" && ifaceName == "error" || ifacePkg == "" && ifaceName == "error" {
			return
		}
		if cat, ok := classifyExternal(ifacePkg, ifaceName, c.Method.Name()); ok {
			if cat != "" {
				f.cat(cat, key+" at "+pos(in))
			}
			return
		}
		if !found {
			f.cat("dynamic-call", "interface call "+key+" at "+pos(in))
		}
		return
	}
	if !found {
		f.cat("dynamic-call", "call of function value at "+pos(in))
	}
}

var ifaceSinks = map[string]string{
	"net/http.RoundTripper.RoundTrip": "net",
	"net.Conn.Write":                  "net",
	"net.Conn.Read":                   "net",
}

func recvName(fn *ssa.Function) string {
	if fn.Signature.Recv() == nil {
		return ""
	}
	t := fn.Signature.Recv().Type()
	if p, ok := t.(*types.Pointer); ok {
		t = p.Elem()
	}
	if n, ok := t.(*types.Named); ok {
		return n.Obj().Name()
	}
	return ""
}

func external(f *Func, sc *ssa.Function, c *ssa.CallCommon, in ssa.CallInstruction) {
	p := pkgOf(sc)
	if p == nil {
		return
	}
	pkg, recv, name := p.Path(), recvName(sc), sc.Name()
	full := pkg + "." + name
	if recv != "" {
		full = pkg + "." + recv + "." + name
	}
	has := func(prefixes ...string) bool {
		for _, pre := range prefixes {
			if strings.HasPrefix(name, pre) {
				return true
			}
		}
		return false
	}
	switch {
	case pkg == "database/sql" && (recv == "DB" || recv == "Tx" || recv == "Conn"):
		if has("Query", "Exec", "Prepare") {
			idx := 1
			if strings.HasSuffix(name, "Context") {
				idx = 2
			}
			sqlCall(f, c, idx, name, full, in)
			return
		}
		f.cat("db-control", full+" at "+pos(in))
		return
	case pkg == "database/sql":
		if recv == "Stmt" && has("Query", "Exec") {
			if len(c.Args) > 0 && preparedHere(c.Args[0]) {
				return // effect was attributed at the Prepare call in this function
			}
			verb := "reads"
			if has("Exec") {
				verb = "writes"
			}
			f.Unres = append(f.Unres, fmt.Sprintf("%s at %s: statement prepared outside this function", full, pos(in)))
			f.add(verb+" ?", full, in, true)
			return
		}
		if name == "Open" || name == "OpenDB" {
			f.cat("db-control", full+" at "+pos(in))
		}
		return
	case pkg == "gorm.io/gorm" && recv == "DB":
		gormCall(f, c, name, full, in)
		return
	case pkg == "gorm.io/gorm" && recv == "Association":
		gormAssoc(f, c, name, full, in)
		return
	case pkg == "gorm.io/gorm":
		if name == "Open" {
			f.cat("db-control", full+" at "+pos(in))
		}
		return
	}
	if e, ok := netSink(pkg, recv, name); ok {
		f.add(e, full, in, false)
		return
	}
	if fsSink(pkg, recv, name) {
		f.add("fs", full, in, false)
		return
	}
	if name == "init" && recv == "" {
		return // dependency package initialiser, run once at program start
	}
	cat, ok := classifyExternal(pkg, recv, name)
	if !ok {
		f.cat("unclassified-external", full+" at "+pos(in))
		return
	}
	if cat != "" {
		f.cat(cat, full+" at "+pos(in))
	}
}

// preparedHere: does this *sql.Stmt come from a Prepare call in the same function?
func preparedHere(v ssa.Value) bool {
	seen := map[ssa.Value]bool{}
	for i := 0; i < 16 && v != nil && !seen[v]; i++ {
		seen[v] = true
		switch x := v.(type) {
		case *ssa.Extract:
			v = x.Tuple
		case *ssa.Call:
			sc := x.Call.StaticCallee()
			return sc != nil && strings.HasPrefix(sc.Name(), "Prepare")
		case *ssa.Phi:
			for _, e := range x.Edges {
				if preparedHere(e) {
					return true
				}
			}
			return false
		default:
			return false
		}
	}
	return false
}

func netSink(pkg, recv, name string) (string, bool) {
	p := func(pre ...string) bool {
		for _, x := range pre {
			if strings.HasPrefix(name, x) {
				return true
			}
		}
		return false
	}
	switch pkg {
	case "net":
		if p("Dial", "Lookup") || (recv == "Dialer" && p("Dial")) || (recv == "Resolver" && p("Lookup")) {
			return "net", true
		}
	case "net/http":
		if recv == "" && (name == "Get" || name == "Post" || name == "PostForm" || name == "Head") {
			return "net", true
		}
		if recv == "Client" && (name == "Do" || name == "Get" || name == "Post" || name == "PostForm" || name == "Head") {
			return "net", true
		}
		if recv == "Transport" && name == "RoundTrip" {
			return "net", true
		}
	case "net/smtp":
		if name == "SendMail" || name == "Dial" || recv == "Client" {
			return "net", true
		}
	case "crypto/tls":
		if p("Dial") {
			return "net", true
		}
	case "golang.org/x/oauth2":
		if (recv == "Config" && (name == "Exchange" || name == "PasswordCredentialsToken")) || name == "Token" {
			return "net", true
		}
	case "github.com/coreos/go-oidc/v3/oidc":
		if name == "NewProvider" || name == "Verify" || name == "UserInfo" {
			return "net", true
		}
	case "golang.org/x/crypto/acme/autocert":
		if recv == "Manager" {
			return "net", true
		}
	}
	return "", false
}

func fsSink(pkg, recv, name string) bool {
	switch pkg {
	case "os":
		switch name {
		case "Open", "OpenFile", "Create", "CreateTemp", "ReadFile", "WriteFile", "Remove", "RemoveAll", "Mkdir", "MkdirAll",
			"MkdirTemp", "Rename", "Stat", "Lstat", "Chmod", "Chown", "ReadDir", "Symlink", "Link", "Truncate", "Readlink", "DirFS", "OpenRoot":
			return true
		}
		if recv == "File" && name != "Fd" && name != "Name" {
			return true
		}
	case "io/ioutil":
		return name != "ReadAll" && name != "NopCloser" && name != "Discard"
	case "path/filepath":
		return name == "Walk" || name == "WalkDir" || name == "Glob" || name == "EvalSymlinks" || name == "Abs"
	case "net/http":
		return name == "ServeFile" || name == "Dir" || name == "FileServer"
	case "html/template", "text/template":
		return name == "ParseFiles" || name == "ParseGlob"
	}
	return false
}

// classifyExternal: ok=false means we know nothing about this callee.
// cat=="" means known not to break purity; otherwise the impurity category.
func classifyExternal(pkg, recv, name string) (cat string, ok bool) {
	switch pkg {
	case "time":
		switch name {
		case "Now", "Since", "Until", "Sleep", "After", "Tick", "NewTimer", "NewTicker", "AfterFunc":
			return "nondeterministic", true
		}
		if recv == "Timer" || recv == "Ticker" {
			return "nondeterministic", true
		}
		return "", true
	case "math/rand", "math/rand/v2", "crypto/rand":
		return "nondeterministic", true
	case "golang.org/x/crypto/bcrypt":
		if name == "GenerateFromPassword" {
			return "nondeterministic", true
		}
		return "", true
	case "os":
		switch name {
		case "Getenv", "LookupEnv", "Environ", "Getpid", "Hostname", "Getwd", "Executable", "Getuid", "Getgid":
			return "reads-environment", true
		case "Exit", "Setenv", "Unsetenv":
			return "process-control", true
		case "IsNotExist", "IsExist", "IsTimeout", "IsPermission", "NewFile", "Fd", "Name":
			return "", true
		}
		return "", false
	case "os/exec", "os/signal", "syscall", "golang.org/x/sys/unix", "golang.org/x/term":
		return "process-control", true
	case "log", "log/slog":
		return "logging", true
	case "sync", "sync/atomic", "golang.org/x/sync/errgroup", "golang.org/x/sync/singleflight":
		return "concurrency", true
	case "runtime", "runtime/debug", "runtime/pprof", "runtime/metrics", "expvar":
		return "reads-environment", true
	case "fmt":
		if strings.HasPrefix(name, "Print") || strings.HasPrefix(name, "Fprint") || strings.HasPrefix(name, "Scan") || strings.HasPrefix(name, "Fscan") {
			return "stream-io", true
		}
		return "", true
	case "io", "bufio":
		// Reads and writes on caller-supplied streams. Not provably pure.
		if pkg == "io" && (name == "NopCloser" || name == "MultiReader" || name == "LimitReader" || name == "TeeReader" || name == "MultiWriter" || name == "NewSectionReader") {
			return "", true
		}
		if pkg == "bufio" && strings.HasPrefix(name, "New") {
			return "", true
		}
		return "stream-io", true
	case "net/http":
		// Server-side request/response plumbing: not outbound net, but not pure either.
		switch recv {
		case "Header", "Cookie", "Request":
			if recv == "Request" && (name == "ParseForm" || name == "ParseMultipartForm" || name == "FormFile" || name == "FormValue" || name == "PostFormValue" || name == "MultipartReader") {
				return "http-server-io", true
			}
			if recv == "Header" && (name == "Set" || name == "Add" || name == "Del") {
				return "http-server-io", true
			}
			return "", true
		case "ResponseWriter", "Server", "ServeMux", "ResponseController":
			return "http-server-io", true
		}
		switch name {
		case "Error", "Redirect", "SetCookie", "NotFound", "ServeContent", "ListenAndServe", "Serve", "Handle", "HandleFunc", "MaxBytesReader", "StripPrefix":
			return "http-server-io", true
		case "NewRequest", "NewRequestWithContext", "StatusText", "CanonicalHeaderKey", "DetectContentType", "ParseHTTPVersion", "ParseTime", "NewServeMux", "HandlerFunc", "ParseCookie", "ParseSetCookie", "NewResponseController":
			return "", true
		}
		return "", false
	case "net":
		if strings.HasPrefix(name, "Listen") || recv == "ListenConfig" || strings.HasSuffix(recv, "Conn") || strings.HasSuffix(recv, "Listener") {
			return "http-server-io", true
		}
		return "", true // parsing helpers (ParseIP, SplitHostPort, IP methods...)
	case "context":
		if name == "WithTimeout" || name == "WithDeadline" || name == "WithCancel" || name == "AfterFunc" || name == "WithCancelCause" {
			return "nondeterministic", true
		}
		return "", true
	case "reflect", "unsafe":
		return "reflection", true
	case "flag":
		return "process-control", true
	case "golang.org/x/net/http/httpproxy":
		return "reads-environment", true
	case "github.com/prometheus/client_golang/prometheus", "github.com/prometheus/client_golang/prometheus/promhttp":
		return "metrics", true
	case "github.com/PuerkitoBio/goquery":
		if strings.HasPrefix(name, "NewDocumentFromReader") {
			return "stream-io", true
		}
		return "", true
	case "github.com/andybalholm/brotli":
		return "stream-io", true
	case "golang.org/x/oauth2":
		if name == "SetAuthURLParam" || name == "AuthCodeURL" || name == "S256ChallengeOption" || name == "VerifierOption" || name == "GenerateVerifier" {
			return "", true
		}
		return "", false
	}
	purePrefixes := []string{"strings", "strconv", "bytes", "unicode", "math", "sort", "slices", "maps", "errors", "regexp",
		"encoding", "html", "text/", "net/url", "net/mail", "net/netip", "net/textproto", "net/http/httputil", "path", "crypto", "hash", "container", "mime", "compress",
		"archive", "image", "cmp", "iter", "embed", "unique", "golang.org/x/text", "golang.org/x/net/html", "golang.org/x/net/idna",
		"golang.org/x/crypto", "golang.org/x/image", "github.com/andybalholm/cascadia", "github.com/tdewolff/minify/v2", "github.com/tdewolff/parse/v2", "github.com/lib/pq", "golang.org/x/net/publicsuffix", "github.com/gosimple/slug", "github.com/go-playground/validator/v10", "github.com/golang-jwt/jwt/v5", "database/sql/driver", "io/fs", "testing", "go/", "internal/"}
	for _, pre := range purePrefixes {
		if pkg == pre || strings.HasPrefix(pkg, pre+"/") || (strings.HasSuffix(pre, "/") && strings.HasPrefix(pkg, pre)) {
			return "", true
		}
	}
	return "", false
}

// paramIndex reports whether v is (possibly via phi) one of fn's own parameters.
func paramIndex(fn *ssa.Function, v ssa.Value) int {
	if p, ok := v.(*ssa.Parameter); ok {
		for i, q := range fn.Params {
			if q == p {
				return i
			}
		}
	}
	return -1
}

func sqlCall(f *Func, c *ssa.CallCommon, idx int, method, full string, in ssa.CallInstruction) {
	if idx < len(c.Args) {
		sqlValue(f, c.Args[idx], method, full, in)
	}
}

// sqlValue attributes the effect of executing the SQL text held in v.
func sqlValue(f *Func, v ssa.Value, method, full string, in ssa.Instruction) {
	if i := paramIndex(f.fn, v); i >= 0 && f.fn.Parent() == nil {
		// The query text is supplied by our callers: attribute the effect at each call site instead.
		if f.sqlPar == nil {
			f.sqlPar = map[int]string{}
		}
		f.sqlPar[i] = method
		return
	}
	var frags []string
	approx := false
	frags, ok := resolveSQL(v, 0, map[ssa.Value]bool{})
	var rw []string
	if ok {
		rw = parseSQL(strings.Join(frags, " ; "))
	}
	if len(rw) == 0 && ok && sqlLike(strings.Join(frags, " ")) {
		text := strings.Join(frags, " ")
		switch {
		case reWriteVerb.MatchString(text):
			// A write statement whose target table could not be determined.
			f.Unres = append(f.Unres, fmt.Sprintf("%s at %s: write statement with unresolved table", full, pos(in)))
			f.add("writes ?", full, in, true)
		case reFromKw.MatchString(text) && !reReads.MatchString(text):
			f.Unres = append(f.Unres, fmt.Sprintf("%s at %s: query with unresolved table", full, pos(in)))
			f.add("reads ?", full, in, true)
		default:
			// Touches no table at all (SELECT version(), SET, advisory locks...).
			f.cat("db-control", "table-less SQL at "+pos(in))
		}
		return
	}
	if len(rw) == 0 {
		// Fallback: SQL-looking constants anywhere in this function (flow-insensitive).
		approx = true
		var pool []string
		for _, s := range funcConsts(f.fn) {
			if sqlLike(s) {
				pool = append(pool, s)
			}
		}
		rw = parseSQL(strings.Join(pool, " ; "))
	}
	if len(rw) == 0 {
		verb := "reads"
		if strings.HasPrefix(method, "Exec") {
			verb = "writes"
		}
		f.Unres = append(f.Unres, fmt.Sprintf("%s at %s: SQL text not statically resolvable", full, pos(in)))
		f.add(verb+" ?", full, in, true)
		return
	}
	for _, e := range rw {
		f.add(e, full, in, approx)
	}
}

// ---------- GORM ----------

func gormNoun(t types.Type) string {
	for {
		switch x := t.(type) {
		case *types.Pointer:
			t = x.Elem()
			continue
		case *types.Slice:
			t = x.Elem()
			continue
		case *types.Array:
			t = x.Elem()
			continue
		}
		break
	}
	n, ok := t.(*types.Named)
	if !ok {
		return ""
	}
	if _, isStruct := n.Underlying().(*types.Struct); !isStruct {
		return ""
	}
	name := strings.TrimSuffix(n.Obj().Name(), "Model")
	var b strings.Builder
	for i, r := range name {
		if r >= 'A' && r <= 'Z' {
			if i > 0 {
				b.WriteByte('_')
			}
			b.WriteRune(r + 32)
		} else {
			b.WriteRune(r)
		}
	}
	s := b.String()
	if strings.HasSuffix(s, "y") {
		return s[:len(s)-1] + "ies"
	}
	if strings.HasSuffix(s, "s") {
		return s
	}
	return s + "s"
}

func underIface(v ssa.Value) types.Type {
	if mi, ok := v.(*ssa.MakeInterface); ok {
		return mi.X.Type()
	}
	return v.Type()
}

// chainNouns walks back along a gorm method chain collecting nouns named by Model(), Table(),
// struct-typed Where() arguments and Preload() paths.
func chainNouns(recv ssa.Value, dest types.Type) (model string, preloads []string) {
	var preloadPaths []string
	seen := map[ssa.Value]bool{}
	var walk func(v ssa.Value)
	walk = func(v ssa.Value) {
		if v == nil || seen[v] {
			return
		}
		seen[v] = true
		switch x := v.(type) {
		case *ssa.Phi:
			for _, e := range x.Edges {
				walk(e)
			}
		case *ssa.UnOp:
			if al, ok := x.X.(*ssa.Alloc); ok {
				for _, r := range *al.Referrers() {
					if st, ok := r.(*ssa.Store); ok {
						walk(st.Val)
					}
				}
			}
		case *ssa.Call:
			sc := x.Call.StaticCallee()
			if sc == nil || pkgOf(sc) == nil || pkgOf(sc).Path() != "gorm.io/gorm" || len(x.Call.Args) == 0 {
				return
			}
			switch sc.Name() {
			case "Model":
				if len(x.Call.Args) > 1 && model == "" {
					model = gormNoun(underIface(x.Call.Args[1]))
					if dest == nil {
						dest = underIface(x.Call.Args[1])
					}
				}
			case "Table":
				if len(x.Call.Args) > 1 && model == "" {
					if c, ok := x.Call.Args[1].(*ssa.Const); ok && c.Value != nil {
						model = constString(c)
					}
				}
			case "Where":
				if len(x.Call.Args) > 1 && model == "" {
					if n := gormNoun(underIface(x.Call.Args[1])); n != "" {
						model = n
					}
				}
			case "Preload", "Joins":
				if len(x.Call.Args) > 1 {
					if c, ok := x.Call.Args[1].(*ssa.Const); ok && c.Value != nil {
						preloadPaths = append(preloadPaths, constString(c))
					}
				}
			}
			walk(x.Call.Args[0])
		}
	}
	walk(recv)
	for _, p := range preloadPaths {
		t := dest
		for _, part := range strings.Split(p, ".") {
			ft := fieldType(t, part)
			if ft == nil {
				break
			}
			if n := gormNoun(ft); n != "" {
				preloads = append(preloads, n)
			}
			t = ft
		}
	}
	return
}

func constString(c *ssa.Const) string {
	s := c.Value.ExactString()
	if u, err := unquote(s); err == nil {
		return u
	}
	return s
}

func fieldType(t types.Type, name string) types.Type {
	if t == nil {
		return nil
	}
	for {
		switch x := t.(type) {
		case *types.Pointer:
			t = x.Elem()
			continue
		case *types.Slice:
			t = x.Elem()
			continue
		}
		break
	}
	st, ok := t.Underlying().(*types.Struct)
	if !ok {
		return nil
	}
	for i := 0; i < st.NumFields(); i++ {
		if st.Field(i).Name() == name {
			return st.Field(i).Type()
		}
	}
	return nil
}

func gormCall(f *Func, c *ssa.CallCommon, name, full string, in ssa.CallInstruction) {
	verbs := map[string][]string{
		"First": {"reads"}, "Find": {"reads"}, "Take": {"reads"}, "Last": {"reads"}, "Count": {"reads"}, "Scan": {"reads"},
		"Pluck": {"reads"}, "Row": {"reads"}, "Rows": {"reads"}, "FindInBatches": {"reads"},
		"Create": {"writes"}, "CreateInBatches": {"writes"}, "Save": {"writes"}, "Update": {"writes"}, "Updates": {"writes"},
		"UpdateColumn": {"writes"}, "UpdateColumns": {"writes"}, "Delete": {"writes"}, "AutoMigrate": {"writes"},
		"FirstOrCreate": {"reads", "writes"}, "FirstOrInit": {"reads"},
	}
	vs, ok := verbs[name]
	if !ok {
		if name == "Exec" || name == "Raw" {
			f.Unres = append(f.Unres, fmt.Sprintf("%s at %s: raw SQL through gorm", full, pos(in)))
			f.add("writes ?", full, in, true)
		}
		if name == "Begin" || name == "Commit" || name == "Rollback" || name == "Transaction" || name == "DB" {
			f.cat("db-control", full+" at "+pos(in))
		}
		return // chain builders (Where, Model, Preload...) have no effect on their own
	}
	var dest types.Type
	noun := ""
	if len(c.Args) > 1 && name != "Count" && name != "Update" && name != "Updates" && name != "UpdateColumn" && name != "UpdateColumns" && name != "Pluck" {
		dest = underIface(c.Args[1])
		noun = gormNoun(dest)
	}
	model, preloads := chainNouns(c.Args[0], dest)
	if noun == "" {
		noun = model
	}
	approx := false
	if noun == "" {
		noun, approx = "?", true
		f.Unres = append(f.Unres, fmt.Sprintf("%s at %s: gorm model type not statically resolvable", full, pos(in)))
	}
	for _, v := range vs {
		f.add(v+" "+noun, full, in, approx)
	}
	for _, p := range preloads {
		f.add("reads "+p, full+" (preload)", in, false)
	}
}

func gormAssoc(f *Func, c *ssa.CallCommon, name, full string, in ssa.CallInstruction) {
	verb := ""
	switch name {
	case "Find", "Count":
		verb = "reads"
	case "Append", "Replace", "Delete", "Clear":
		verb = "writes"
	default:
		return
	}
	// receiver is the result of db.Model(x).Association("Field")
	noun, owner := "?", ""
	if call, ok := c.Args[0].(*ssa.Call); ok && len(call.Call.Args) > 1 {
		field := ""
		if k, ok := call.Call.Args[1].(*ssa.Const); ok && k.Value != nil {
			field = constString(k)
		}
		var mt types.Type
		seen := map[ssa.Value]bool{}
		var walk func(v ssa.Value)
		walk = func(v ssa.Value) {
			if seen[v] {
				return
			}
			seen[v] = true
			if cc, ok := v.(*ssa.Call); ok {
				if sc := cc.Call.StaticCallee(); sc != nil && sc.Name() == "Model" && len(cc.Call.Args) > 1 {
					mt = underIface(cc.Call.Args[1])
					return
				}
				if len(cc.Call.Args) > 0 {
					walk(cc.Call.Args[0])
				}
			}
		}
		walk(call.Call.Args[0])
		owner = gormNoun(mt)
		if ft := fieldType(mt, field); ft != nil {
			if n := gormNoun(ft); n != "" {
				noun = n
			}
		}
	}
	if noun == "?" {
		f.Unres = append(f.Unres, fmt.Sprintf("%s at %s: association target not resolvable", full, pos(in)))
	}
	f.add(verb+" "+noun, full, in, noun == "?")
	if verb == "writes" && owner != "" && noun != "?" {
		// many2many join rows
		f.add("writes "+strings.TrimSuffix(owner, "s")+"_"+noun, full+" (join table)", in, true)
	}
}

// ---------- propagation ----------

// forwardSQL resolves SQL text passed through helper parameters, at the call sites that supply it.
func forwardSQL() {
	for changed := true; changed; {
		changed = false
		for _, f := range funcs {
			for _, cs := range f.calls {
				if cs.in == nil {
					continue
				}
				for i, method := range cs.callee.sqlPar {
					if cs.done[i] || i >= len(cs.args) {
						continue
					}
					cs.done[i] = true
					changed = true
					sqlValue(f, cs.args[i], method, "database/sql (via "+cs.callee.ID+")", cs.in)
				}
			}
		}
	}
}

// orphanSQL flags functions that execute caller-supplied SQL but have no module call sites
// supplying it (adopted from Fable's effects-fixes.patch).
func orphanSQL() {
	sites := map[*Func]int{}
	for _, f := range funcs {
		for _, cs := range f.calls {
			if cs.in != nil {
				sites[cs.callee]++
			}
		}
	}
	for _, f := range funcs {
		for i, method := range f.sqlPar {
			if sites[f] > 0 {
				continue
			}
			verb := "reads"
			if strings.HasPrefix(method, "Exec") {
				verb = "writes"
			}
			f.Unres = append(f.Unres, fmt.Sprintf("executes SQL from parameter %d, no call sites found", i))
			f.eff[verb+" ?"] = true
		}
	}
}

func propagate() {
	for _, f := range funcs {
		for _, cs := range f.calls {
			f.callees[cs.callee] = true
			cs.callee.callers[f] = true
		}
	}
	for changed := true; changed; {
		changed = false
		for _, f := range funcs {
			for _, cs := range f.calls {
				t := cs.callee
				for e := range t.eff {
					if !f.eff[e] {
						f.eff[e], changed = true, true
					}
					if t.exact[e] && !f.exact[e] {
						f.exact[e], changed = true, true
					}
				}
				for c, ex := range t.cats {
					if _, ok := f.cats[c]; !ok {
						f.cats[c], changed = "via "+t.ID+": "+strings.TrimPrefix(ex, "via "), true
						if i := strings.Index(f.cats[c][4:], ": via "); i >= 0 {
							f.cats[c] = f.cats[c][:4+i] // keep one hop only
						}
					}
				}
				if t.mutPar {
					// Mutation of the callee's params matters to us only if what we passed is not our own local.
					if cs.args == nil {
						if !f.mutPar {
							f.mutPar, f.mutEx, changed = true, "via closure "+t.ID, true
						}
						continue
					}
					for _, a := range cs.args {
						if !pointerLike(a.Type()) {
							continue
						}
						_, kind := base(a)
						switch kind {
						case "param":
							if !f.mutPar {
								f.mutPar, f.mutEx, changed = true, "passes own param/receiver to mutating "+t.ID, true
							}
						case "global":
							if _, ok := f.cats["writes-global"]; !ok {
								f.cats["writes-global"], changed = "passes global to mutating "+t.ID, true
							}
						case "unknown":
							if _, ok := f.cats["writes-unknown-pointer"]; !ok {
								f.cats["writes-unknown-pointer"], changed = "passes pointer of unknown origin to mutating "+t.ID, true
							}
						}
					}
				}
			}
		}
	}
}

// ---------- output ----------

func emit(out string) {
	var list []*Func
	for _, f := range funcs {
		list = append(list, f)
	}
	sort.Slice(list, func(i, j int) bool { return list[i].ID < list[j].ID })
	ids := func(m map[*Func]bool) []string {
		s := []string{}
		for f := range m {
			s = append(s, f.ID)
		}
		sort.Strings(s)
		return s
	}
	for _, f := range list {
		f.Inferred = []string{}
		for e := range f.eff {
			f.Inferred = append(f.Inferred, e)
		}
		sort.Slice(f.Inferred, func(i, j int) bool { return effKey(f.Inferred[i]) < effKey(f.Inferred[j]) })
		for e := range f.eff {
			if !f.exact[e] {
				f.InfApprox = append(f.InfApprox, e)
			}
		}
		sort.Strings(f.InfApprox)
		if f.mutPar {
			f.Mut, f.MutWhy = true, f.mutEx
			f.Inferred = append(f.Inferred, "mut")
		}
		for c, ex := range f.cats {
			if ambient[c] {
				f.Ambient = append(f.Ambient, c)
				continue
			}
			f.Impure = append(f.Impure, c)
			f.ImpureEx = append(f.ImpureEx, c+": "+ex)
		}
		sort.Strings(f.Ambient)
		sort.Strings(f.Impure)
		sort.Strings(f.ImpureEx)
		f.Pure = len(f.Inferred) == 0 && len(f.Impure) == 0
		f.Callees, f.Callers, f.Refs = ids(f.callees), ids(f.callers), ids(f.refs)
		sort.Slice(f.Direct, func(i, j int) bool { return f.Direct[i].Pos < f.Direct[j].Pos })
	}
	tl := []string{}
	for t := range tables {
		tl = append(tl, t)
	}
	sort.Strings(tl)
	doc := map[string]any{"module": modPath, "tables": tl, "functions": list}
	b, _ := json.MarshalIndent(doc, "", " ")
	if err := os.WriteFile(out, b, 0o644); err != nil {
		fatal(err)
	}
	fmt.Printf("%d functions, %d tables -> %s\n", len(list), len(tl), out)
}

// ambient impurity: real, but deliberately outside the tag vocabulary (decision 2026-11-11, item 4).
var ambient = map[string]bool{"logging": true, "nondeterministic": true, "concurrency": true, "http-server-io": true, "stream-io": true}

func effKey(e string) string {
	order := map[string]string{"reads": "1", "writes": "2", "net": "3", "fs": "4", "mut": "5"}
	return order[strings.Fields(e)[0]] + e
}
