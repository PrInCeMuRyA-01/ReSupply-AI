"""A request-bound shop scope. A page cannot change another tab's workspace."""
from contextvars import ContextVar
from contextlib import contextmanager

from starlette.responses import RedirectResponse

_workspace = ContextVar('resupply_workspace', default='real')


def is_demo_shop():
    return _workspace.get() == 'demo'


def planning_source():
    return 'demo' if is_demo_shop() else 'actual'


@contextmanager
def demo_scope():
    token = _workspace.set('demo')
    try:
        yield
    finally:
        _workspace.reset(token)


def order_number(connection, order_id):
    if not is_demo_shop():
        row = connection.execute("SELECT value FROM easy_settings WHERE key='namespace'").fetchone()
        if not row: raise RuntimeError('Shop identity is missing. Restart the server.')
        return f"EASY-{row['value']}-{order_id:06d}"
    row = connection.execute("SELECT value FROM demo_shop_settings WHERE key='namespace'").fetchone()
    if not row:
        raise RuntimeError('Demo shop identity is missing. Restart the server.')
    # Durable namespace also binds PayPal reference/custom/invoice IDs. Copies
    # of one demo DB retain the same identity; a new DB gets a new identity.
    return f"DEMO-{row['value']}-{order_id:06d}"


class ShopWorkspaceMiddleware:
    """Reuse the same routes under /demo with an isolated ContextVar and DB."""
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http':
            return await self.app(scope, receive, send)
        root = scope.get('root_path', '').rstrip('/')
        path = scope['path']
        if root and path.startswith(root + '/'):
            path = path[len(root):]
        demo = path == '/demo' or path.startswith('/demo/')
        if path == '/demo' and scope['method'] in ('GET', 'HEAD'):
            return await RedirectResponse(root+'/demo/', status_code=307)(scope, receive, send)
        child = dict(scope)
        if demo:
            child['root_path'] = root + '/demo'
            child['path'] = child['root_path'] + (path[len('/demo'):] or '/')
            child['raw_path'] = child['path'].encode('utf-8')
            # Router strips root_path, while slash redirects retain /demo.
            # Do not mutate app.root_path: it is shared by concurrent shops.
        token = _workspace.set('demo' if demo else 'real')
        async def scoped_send(message):
            if message['type'] == 'http.response.start':
                message = {**message, 'headers': [*message.get('headers', []),
                    (b'x-resupply-workspace', b'demo' if demo else b'real'),
                    (b'cache-control', b'no-store')]}
            await send(message)
        try:
            await self.app(child, receive, scoped_send)
        finally:
            _workspace.reset(token)
