from aiohttp import web
import aiofiles
import asyncio
import datetime
import os
import signal
import logging
from multidict import CIMultiDict


INTERVAL_SECS = 1


async def uptime_handler(request):

    response = web.StreamResponse()

    # Большинство браузеров не отрисовывают частично загруженный контент,
    # только если это не HTML.
    # Поэтому отправляем клиенту именно HTML, указываем это в Content-Type.
    response.headers['Content-Type'] = 'text/html'

    # Отправляет клиенту HTTP заголовки
    await response.prepare(request)

    while True:
        formatted_date = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        message = f'{formatted_date}<br>'  # <br> — HTML тег переноса строки

        # Отправляет клиенту очередную порцию ответа
        await response.write(message.encode('utf-8'))

        await asyncio.sleep(INTERVAL_SECS)


async def on_shutdown(app):
    for ws in set(app['websockets']):
        await ws.close(code=WSCloseCode.GOING_AWAY,
                       message='Server shutdown')


async def stream_archivation(request):
    response = web.StreamResponse()
    response.headers['Content-Type'] = 'application/zip'
    response.headers['Content-Disposition'] = 'attachment; filename="archive.zip"'
    request_folder = request.path.split('/')[-2]
    if not request_folder in os.listdir('test_photos'):
        raise web.HTTPNotFound(body=('404 ERROR.\nRequested archive doesnt '
                                     'exist or was deleted'))
    await response.prepare(request)
    path = os.path.join('test_photos', request_folder)
    filenames = get_filenames(path)
    args = 'zip -r - ' + filenames
    process = await asyncio.create_subprocess_shell(args,
                                                    stdout=asyncio.subprocess.PIPE,
                                                    limit=800,
                                                    preexec_fn=os.setsid)
    try:
        async for chunk in archivate(filenames, process):
            await response.write(chunk)
            await asyncio.sleep(1)
        return response
    except asyncio.CancelledError as err:
        print('Caught CancelledError from stream archivation')
        os.killpg(os.getpgid(process.pid), signal.SIGTERM)
        raise
    finally:
        response.force_close()


def get_filenames(path):
    return ' '.join([os.path.join(path, filename) for filename in os.listdir(path)])


async def archivate(filenames, archivation_process):
    while True:
        chunk = await archivation_process.stdout.read(800)
        if not chunk:
            break
        yield chunk


async def handle_index_page(request):
    async with aiofiles.open('index.html', mode='r') as index_file:
        index_contents = await index_file.read()
    return web.Response(text=index_contents, content_type='text/html')


async def write_to_file():
    with open('archive.zip', 'ab') as archive:
        async for chunk in  archivate():
            archive.write(chunk)


if __name__ == '__main__':
    logger = logging.getLogger()
    logger.setLevel(logging.DEBUG)
    app = web.Application()
    app.add_routes([
        web.get('/', handle_index_page),
        web.get('/archive/{archive_hash}/', stream_archivation),
    ])
    app.on_shutdown.append(on_shutdown)
    try:
        web.run_app(app)
    except Exception as err:
        print('Caught RuntimeError')
    finally:
        loop = asyncio.get_event_loop()
        loop.close()
    #loop.run_until_complete(write_to_file())
    #loop.close()
