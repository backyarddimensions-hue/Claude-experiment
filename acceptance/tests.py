"""Hidden acceptance tests, one function per task. Written from the task text in TASKS.md only,
before any agent run. Each test receives a Ctx with a fresh database and decides when to start
the server."""
import time
from lib import item

BASELINE_FEED_COLS = None  # filled by run.py from a database migrated by the unmodified binary
BASELINE_ENTRY_COLS = None


def secs_until(ctx, feed_id):
    r = ctx.psql(f'select extract(epoch from (next_check_at - now())) from feeds where id={feed_id}')
    return float(r[0][0])


# ---------------------------------------------------------------- task 0 (shakedown, unscored)
def task0(ctx):
    ctx.start()
    fid = ctx.make_feed('t0', [item('a'), item('b'), item('c')])
    s, j = ctx.api('GET', f'/v1/feeds/{fid}/entries/count')
    ctx.check('endpoint returns 200', s == 200, f'{s} {j}')
    ctx.check('count equals number of entries', isinstance(j, dict) and j.get('count') == 3, j)
    s, _ = ctx.api('GET', '/v1/feeds/999999/entries/count')
    ctx.check('unknown feed returns 404', s == 404, s)
    ctx.api('POST', '/v1/users', {'username': 'bob', 'password': 'secret123'})
    s, _ = ctx.api('GET', f'/v1/feeds/{fid}/entries/count', user='bob', password='secret123')
    ctx.check("another user's feed returns 404", s == 404, s)


# ---------------------------------------------------------------- task 1: per-feed fetch interval
def task1(ctx):
    ctx.start()
    new_cols = ctx.columns('feeds') - BASELINE_FEED_COLS
    ctx.check('migration added a column to feeds', len(new_cols) >= 1, new_cols)
    plain = ctx.make_feed('t1plain', [item('p')])
    over = ctx.make_feed('t1over', [item('o')])
    s, j = ctx.api('GET', f'/v1/feeds/{plain}')
    ctx.check('API exposes refresh_interval, 0 by default', isinstance(j, dict) and j.get('refresh_interval') == 0, (j or {}).get('refresh_interval', 'missing') if isinstance(j, dict) else j)
    s, j = ctx.api('PUT', f'/v1/feeds/{over}', {'refresh_interval': 137})
    ctx.check('API accepts refresh_interval on update', s in (200, 201) and isinstance(j, dict) and j.get('refresh_interval') == 137, f'{s} {(j or {}).get("refresh_interval", "missing") if isinstance(j, dict) else j}')
    s, j = ctx.api('GET', f'/v1/feeds/{over}')
    ctx.check('value persists', isinstance(j, dict) and j.get('refresh_interval') == 137, s)
    try:
        html = ctx.ui_session().open(f'{ctx.base}/feed/{over}/edit', timeout=20).read().decode()
        ctx.check('UI edit form has a refresh_interval input', 'name="refresh_interval"' in html, 'not found in /feed/{id}/edit')
    except Exception as e:
        ctx.check('UI edit form has a refresh_interval input', False, e)
    ctx.api('PUT', f'/v1/feeds/{over}/refresh')
    ctx.api('PUT', f'/v1/feeds/{plain}/refresh')
    d_over, d_plain = secs_until(ctx, over) / 60, secs_until(ctx, plain) / 60
    ctx.info.update(next_check_minutes_override=round(d_over, 1), next_check_minutes_default=round(d_plain, 1))
    ctx.check('scheduler uses the per-feed interval (137 min)', abs(d_over - 137) <= 3, f'{d_over:.1f} min')
    ctx.check('feeds without an override keep the global interval', abs(d_plain - 137) > 10, f'{d_plain:.1f} min')


# ---------------------------------------------------------------- task 2: entry word count
def task2(ctx):
    # Entries that exist before the upgrade are created by the unmodified binary.
    ctx.start(binary=ctx.baseline)
    old = ctx.make_feed('t2old', [item('old one', content='<p>alpha beta gamma delta</p>')])
    ctx.stop()
    ctx.start()                       # the modified binary migrates the same database
    new_cols = ctx.columns('entries') - BASELINE_ENTRY_COLS
    ctx.check('migration added a column to entries', len(new_cols) >= 1, new_cols)
    s, j = ctx.api('GET', f'/v1/feeds/{old}/entries')
    e = (j or {}).get('entries', [{}])[0] if isinstance(j, dict) else {}
    ctx.check('existing entry has word_count null or backfilled (4)', 'word_count' in e and e['word_count'] in (None, 4), e.get('word_count', 'missing'))
    new = ctx.make_feed('t2new', [item('seven', content='<p>one two three four five six seven</p>'),
                                  item('three', content='red green blue')])
    s, j = ctx.api('GET', f'/v1/feeds/{new}/entries')
    got = {x['title']: x.get('word_count', 'missing') for x in (j or {}).get('entries', [])} if isinstance(j, dict) else {}
    ctx.check('new entries have word_count populated', got == {'seven': 7, 'three': 3}, got)
    eid = j['entries'][0]['id'] if isinstance(j, dict) and j.get('entries') else 0
    s, one = ctx.api('GET', f'/v1/entries/{eid}')
    ctx.check('single-entry endpoint exposes word_count', isinstance(one, dict) and isinstance(one.get('word_count'), int), s)


# ---------------------------------------------------------------- task 3: per-user feed limit
def task3(ctx):
    ctx.start()
    bob, carol = dict(user='bob', password='secret123'), dict(user='carol', password='secret123')
    _, ub = ctx.api('POST', '/v1/users', {'username': 'bob', 'password': 'secret123'})
    _, uc = ctx.api('POST', '/v1/users', {'username': 'carol', 'password': 'secret123'})

    def feeds_of(uid):
        return int(ctx.psql(f'select count(*) from feeds where user_id={uid}')[0][0])

    def limit_of(uid):
        j = ctx.api('GET', f'/v1/users/{uid}')[1]
        return j.get('max_feeds', 'missing') if isinstance(j, dict) else j

    ctx.check('user object has max_feeds, 0 by default', limit_of(ub['id']) == 0, limit_of(ub['id']))
    s, j = ctx.api('PUT', f'/v1/users/{ub["id"]}', {'max_feeds': 2})
    ctx.check('administrator can set max_feeds', s in (200, 201) and limit_of(ub['id']) == 2, f'{s} -> {limit_of(ub["id"])}')
    s, _ = ctx.api('PUT', f'/v1/users/{ub["id"]}', {'max_feeds': 50}, **bob)
    ctx.check('non-admin cannot change own limit', limit_of(ub['id']) == 2, f'http {s}, limit now {limit_of(ub["id"])}')

    s1, _ = ctx.try_feed('t3b1', auth=bob)
    s2, _ = ctx.try_feed('t3b2', auth=bob)
    ctx.check('feeds up to the limit are created', s1 in (200, 201) and s2 in (200, 201) and feeds_of(ub['id']) == 2, f'{s1} {s2}, {feeds_of(ub["id"])} feeds')
    s3, _ = ctx.try_feed('t3b3', auth=bob)
    ctx.check('create beyond the limit is 4xx and creates nothing', 400 <= s3 < 500 and feeds_of(ub['id']) == 2, f'http {s3}, {feeds_of(ub["id"])} feeds')
    s, _ = ctx.api('POST', '/v1/import', raw=ctx.opml(['t3bi1', 't3bi2']), **bob)
    ctx.check('import at the limit adds nothing', feeds_of(ub['id']) == 2, f'http {s}, {feeds_of(ub["id"])} feeds')

    ctx.api('PUT', f'/v1/users/{uc["id"]}', {'max_feeds': 3})
    ctx.make_feed('t3c1', [item('c1')], auth=carol)
    s, _ = ctx.api('POST', '/v1/import', raw=ctx.opml(['t3ci1']), **carol)
    ctx.check('import below the limit still works', s in (200, 201) and feeds_of(uc['id']) == 2, f'http {s}, {feeds_of(uc["id"])} feeds')
    s, _ = ctx.api('POST', '/v1/import', raw=ctx.opml(['t3ci2', 't3ci3', 't3ci4']), **carol)
    ctx.check('import never leaves more than max_feeds', feeds_of(uc['id']) <= 3, f'http {s}, {feeds_of(uc["id"])} feeds')
    s, _ = ctx.try_feed('t3admin')
    ctx.check('a user with max_feeds 0 is unlimited', s in (200, 201), s)


# ---------------------------------------------------------------- task 4: rotate API keys
def task4(ctx):
    ctx.start()
    s, key = ctx.api('POST', '/v1/api-keys', {'description': 'rotate me'})
    old = key['token']
    s, _ = ctx.api('GET', '/v1/me', token=old)
    ctx.check('original key works', s == 200, s)
    s, j = ctx.api('POST', f'/v1/api-keys/{key["id"]}/regenerate')
    new = j.get('token') if isinstance(j, dict) else None
    ctx.check('regenerate endpoint returns a new token', s in (200, 201) and bool(new) and new != old, f'{s} {j}')
    s, _ = ctx.api('GET', '/v1/me', token=old)
    ctx.check('old key fails immediately', s == 401, s)
    s, _ = ctx.api('GET', '/v1/me', token=new) if new else (0, None)
    ctx.check('new key works', s == 200, s)


# ---------------------------------------------------------------- task 5: fetch timeout per feed
def refresh_timed(ctx, fid):
    t = time.time()
    s, j = ctx.api('PUT', f'/v1/feeds/{fid}/refresh', timeout=90)
    return s, time.time() - t


def task5(ctx):
    # Phase 1: global timeout long (30 s), per-feed override short (2 s), server answers after 6 s.
    ctx.start(env={'HTTP_CLIENT_TIMEOUT': '30'})
    short = ctx.make_feed('t5short', [item('s')])
    plain = ctx.make_feed('t5plain', [item('p')])
    s, j = ctx.api('PUT', f'/v1/feeds/{short}', {'fetch_timeout': 2})
    ctx.check('API accepts fetch_timeout', s in (200, 201) and isinstance(j, dict) and j.get('fetch_timeout') == 2, f'{s} {(j or {}).get("fetch_timeout", "missing") if isinstance(j, dict) else j}')
    ctx.feeds.feeds['t5short']['delay'] = 6
    ctx.feeds.feeds['t5plain']['delay'] = 6
    s, dt = refresh_timed(ctx, short)
    ctx.info['phase1_override_seconds'] = round(dt, 1)
    ctx.check('slow feed times out at the per-feed value (2 s), not the global 30 s', s >= 400 and 1.5 <= dt <= 5, f'status {s} after {dt:.1f}s')
    s, dt = refresh_timed(ctx, plain)
    ctx.info['phase1_default_seconds'] = round(dt, 1)
    ctx.check('feed without override still uses the global timeout', s < 400 and dt >= 5.5, f'status {s} after {dt:.1f}s')
    # Phase 2: global timeout short (3 s), per-feed override long (20 s), server answers after 6 s.
    ctx.stop()
    ctx.feeds.feeds['t5short']['delay'] = 0
    ctx.start(env={'HTTP_CLIENT_TIMEOUT': '3'})
    ctx.api('PUT', f'/v1/feeds/{short}', {'fetch_timeout': 20})
    ctx.feeds.feeds['t5short']['delay'] = 6
    s, dt = refresh_timed(ctx, short)
    ctx.info['phase2_override_seconds'] = round(dt, 1)
    ctx.check('per-feed value also overrides a shorter global timeout', s < 400 and dt >= 5.5, f'status {s} after {dt:.1f}s')


# ---------------------------------------------------------------- task 6: audit log
def task6(ctx):
    ctx.start()
    try:
        ctx.psql('select count(*) from audit_log')
        ctx.check('audit_log table exists', True)
    except Exception as e:
        ctx.check('audit_log table exists', False, e)
        ctx.info['paths_found'] = 0
        return

    def rows():
        return int(ctx.psql('select count(*) from audit_log')[0][0])

    found = {}

    def step(name, fn, expect_write=True):
        before = rows()
        status = fn()
        delta = rows() - before
        found[name] = delta >= 1
        return status, delta

    cat = ctx.api('GET', '/v1/categories')[1][0]['id']
    ctx.feeds.feeds['t6a'] = {'items': [item('a1')]}
    ctx.feeds.feeds['t6imp'] = {'items': [item('i1')]}
    ids = {}

    def create_user():
        s, j = ctx.api('POST', '/v1/users', {'username': 'carol', 'password': 'secret123'}); ids['u'] = j['id']; return s
    def create_feed():
        s, j = ctx.api('POST', '/v1/feeds', {'feed_url': ctx.feeds.url('t6a'), 'category_id': cat}); ids['f'] = j['feed_id']; return s
    def refresh_fail():
        ctx.feeds.feeds['t6a']['status'] = 500
        s, _ = ctx.api('PUT', f'/v1/feeds/{ids["f"]}/refresh'); ctx.feeds.feeds['t6a']['status'] = 200; return s
    opml = (f'<?xml version="1.0" encoding="UTF-8"?><opml version="2.0"><body><outline text="All">'
            f'<outline type="rss" text="imp" title="imp" xmlUrl="{ctx.feeds.url("t6imp")}" htmlUrl="http://127.0.0.1/"/></outline></body></opml>').encode()

    paths = [
        ('1 POST /v1/users', create_user),
        ('2 PUT /v1/users/{id}', lambda: ctx.api('PUT', f'/v1/users/{ids["u"]}', {'theme': 'dark_serif'})[0]),
        ('4 POST /v1/feeds', create_feed),
        ('5 PUT /v1/feeds/{id}', lambda: ctx.api('PUT', f'/v1/feeds/{ids["f"]}', {'title': 'renamed'})[0]),
        ('7a PUT /v1/feeds/{id}/refresh (success)', lambda: ctx.api('PUT', f'/v1/feeds/{ids["f"]}/refresh')[0]),
        ('7b PUT /v1/feeds/{id}/refresh (fetch fails, error recorded on feed)', refresh_fail),
        ('8 POST /v1/import', lambda: ctx.api('POST', '/v1/import', raw=opml)[0]),
        ('6 DELETE /v1/feeds/{id}', lambda: ctx.api('DELETE', f'/v1/feeds/{ids["f"]}')[0]),
        ('3 DELETE /v1/users/{id}', lambda: ctx.api('DELETE', f'/v1/users/{ids["u"]}')[0]),
    ]
    for name, fn in paths:
        try:
            status, delta = step(name, fn)
            ctx.check(name + ' appends an audit row', delta >= 1, f'http {status}, {delta} new rows')
        except Exception as e:
            found[name] = False
            ctx.check(name + ' appends an audit row', False, e)
    # the eight ground-truth paths; path 7 needs both of its writers
    eight = {n.split()[0].rstrip('ab') for n, ok in found.items() if ok and not n.startswith('7')}
    if found.get(paths[4][0]) and found.get(paths[5][0]):
        eight.add('7')
    ctx.info['paths_found'] = len(eight)
    ctx.info['paths_found_list'] = sorted(eight)
    # not gating: the task text does not forbid extra rows, but a log-everything solution is worth knowing about
    before = rows(); ctx.api('GET', '/v1/me'); ctx.api('GET', '/v1/feeds')
    ctx.check('read-only requests append nothing', rows() == before, f'{rows() - before} rows for two GETs', gating=False)


TESTS = {'0': task0, '1': task1, '2': task2, '3': task3, '4': task4, '5': task5, '6': task6}
