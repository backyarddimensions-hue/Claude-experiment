"""Shared machinery for the hidden acceptance tests.

Nothing here is visible to an agent: this directory is outside every run's working tree and no
arm has a shell or network tool.
"""
import base64, http.cookiejar, json, os, re, subprocess, threading, time, urllib.error, urllib.parse, urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

EXP = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENV = f'source "{EXP}/scripts/env.sh"; '
PG = 'postgres://postgres@127.0.0.1:55432/%s?sslmode=disable'


def sh(cmd, **kw):
    return subprocess.run(['bash', '-c', ENV + cmd], capture_output=True, text=True, **kw)


def build(tree, out):
    r = sh(f'cd "{tree}" && go build -o "{out}" .')
    if r.returncode:
        raise RuntimeError('build failed:\n' + r.stderr[-3000:])
    return out


class FeedServer:
    """Local RSS server. feeds[name] = dict(items=[dict(title, author, content, guid)], delay=0, status=200)."""

    def __init__(self, port):
        self.port, self.feeds, self.hits = port, {}, []
        outer = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_GET(self):
                name = self.path.strip('/').split('?')[0].removesuffix('.xml')
                f = outer.feeds.get(name)
                outer.hits.append((name, time.time()))
                if f is None:
                    self.send_response(404); self.end_headers(); return
                if f.get('delay'):
                    time.sleep(f['delay'])
                if f.get('status', 200) != 200:
                    self.send_response(f['status']); self.end_headers(); return
                items = ''.join(
                    f'<item><title>{i["title"]}</title><link>http://127.0.0.1:{outer.port}/post/{i["guid"]}</link>'
                    f'<guid>{i["guid"]}</guid><author>{i.get("author", "")}</author>'
                    f'<description><![CDATA[{i.get("content", "")}]]></description>'
                    f'<pubDate>Wed, 11 Nov 2026 10:00:00 GMT</pubDate></item>' for i in f['items'])
                body = (f'<?xml version="1.0" encoding="UTF-8"?><rss version="2.0"><channel><title>{name}</title>'
                        f'<link>http://127.0.0.1:{outer.port}/site/{name}</link><description>{name}</description>{items}</channel></rss>').encode()
                try:
                    self.send_response(200)
                    self.send_header('Content-Type', 'application/rss+xml')
                    self.send_header('Content-Length', str(len(body)))
                    self.end_headers(); self.wfile.write(body)
                except (BrokenPipeError, ConnectionResetError):
                    pass

        self.httpd = ThreadingHTTPServer(('127.0.0.1', port), H)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def url(self, name):
        return f'http://127.0.0.1:{self.port}/{name}.xml'

    def stop(self):
        self.httpd.shutdown()


class Ctx:
    def __init__(self, binary, port, db, feed_port):
        self.binary, self.port, self.db = binary, port, db
        self.base = f'http://127.0.0.1:{port}'
        self.feeds = FeedServer(feed_port)
        self.proc = None
        self.checks = []
        self.info = {}

    # ---- database
    def psql(self, sql):
        r = sh(f'psql -At -F "|" -d {self.db} -c "$SQL"', env={**os.environ, 'SQL': sql})
        if r.returncode:
            raise RuntimeError('psql: ' + r.stderr.strip())
        return [l.split('|') for l in r.stdout.strip().split('\n') if l]

    def reset_db(self):
        sh(f'psql -q -c "drop database if exists {self.db};" -c "create database {self.db};"')

    def columns(self, table):
        return {r[0] for r in self.psql(f"select column_name from information_schema.columns where table_name='{table}'")}

    # ---- server lifecycle
    def start(self, binary=None, env=None):
        e = {**os.environ, 'DATABASE_URL': PG % self.db, 'LISTEN_ADDR': f'127.0.0.1:{self.port}', 'ADMIN_USERNAME': 'admin',
             'ADMIN_PASSWORD': 'test123', 'CREATE_ADMIN': '1', 'RUN_MIGRATIONS': '1', 'LOG_LEVEL': 'debug',
             'FETCHER_ALLOW_PRIVATE_NETWORKS': '1', 'INTEGRATION_ALLOW_PRIVATE_NETWORKS': '1', **(env or {})}
        self.log = open(f'/tmp/exp-accept-{self.port}.log', 'a')
        self.proc = subprocess.Popen([binary or self.binary], env=e, stdout=self.log, stderr=self.log)
        for _ in range(80):
            if self.proc.poll() is not None:
                raise RuntimeError('server exited during startup; see ' + self.log.name)
            try:
                urllib.request.urlopen(self.base + '/healthcheck', timeout=1); return
            except Exception:
                time.sleep(0.25)
        raise RuntimeError('server did not start')

    def stop(self):
        if self.proc:
            self.proc.terminate()
            try:
                self.proc.wait(10)
            except subprocess.TimeoutExpired:
                self.proc.kill()
            self.proc = None

    def close(self):
        self.stop(); self.feeds.stop()
        sh(f'psql -q -c "drop database if exists {self.db};"')

    # ---- HTTP API
    def api(self, method, path, body=None, user='admin', password='test123', token=None, raw=None, timeout=60):
        req = urllib.request.Request(self.base + path, method=method)
        if token:
            req.add_header('X-Auth-Token', token)
        elif user:
            req.add_header('Authorization', 'Basic ' + base64.b64encode(f'{user}:{password}'.encode()).decode())
        data = raw
        if body is not None:
            data = json.dumps(body).encode(); req.add_header('Content-Type', 'application/json')
        try:
            with urllib.request.urlopen(req, data=data, timeout=timeout) as r:
                status, text = r.status, r.read().decode()
        except urllib.error.HTTPError as e:
            status, text = e.code, e.read().decode()
        try:
            return status, json.loads(text) if text else None
        except ValueError:
            return status, text

    def try_feed(self, name, items=None, auth=None, **extra):
        """POST /v1/feeds; returns (status, body). auth = dict(user=..., password=...)."""
        auth = auth or {}
        self.feeds.feeds[name] = {'items': items or [item(name + ' post')]}
        cat = self.api('GET', '/v1/categories', **auth)[1][0]['id']
        return self.api('POST', '/v1/feeds', {'feed_url': self.feeds.url(name), 'category_id': cat, **extra}, **auth)

    def make_feed(self, name, items, auth=None, **extra):
        s, j = self.try_feed(name, items, auth, **extra)
        if s not in (200, 201):
            raise RuntimeError(f'could not create feed {name}: {s} {j}')
        return j['feed_id']

    def opml(self, names):
        for n in names:
            self.feeds.feeds.setdefault(n, {'items': [item(n + ' post')]})
        outlines = ''.join(f'<outline type="rss" text="{n}" title="{n}" xmlUrl="{self.url_of(n)}" htmlUrl="http://127.0.0.1/"/>' for n in names)
        return f'<?xml version="1.0" encoding="UTF-8"?><opml version="2.0"><body><outline text="All">{outlines}</outline></body></opml>'.encode()

    def url_of(self, name):
        return self.feeds.url(name)

    # ---- web UI
    def ui_session(self):
        jar = http.cookiejar.CookieJar()
        op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
        html = op.open(self.base + '/', timeout=20).read().decode()
        m = re.search(r'name="csrf"\s+value="([^"]+)"', html)
        data = urllib.parse.urlencode({'csrf': m.group(1) if m else '', 'username': 'admin', 'password': 'test123'}).encode()
        op.open(self.base + '/login', data=data, timeout=20).read()
        return op

    # ---- results
    def check(self, name, ok, detail='', gating=True):
        self.checks.append({'name': name, 'ok': bool(ok), 'gating': gating, 'detail': str(detail)[:400]})
        return bool(ok)

    def result(self):
        return {'pass': all(c['ok'] for c in self.checks if c['gating']) and bool(self.checks), 'checks': self.checks, 'info': self.info}


def item(title, author='Alice', content='hello', guid=None):
    return {'title': title, 'author': author, 'content': content, 'guid': guid or re.sub(r'\W+', '-', title)}
