import sys, threading, webbrowser
import uvicorn

def open_browser(): webbrowser.open('http://127.0.0.1:8787')
if __name__ == '__main__':
    if sys.argv[1:] == ['--mina-xslt-worker']:
        from app.mapper_xml import xslt_worker
        raise SystemExit(xslt_worker())
    threading.Timer(1.2, open_browser).start()
    uvicorn.run('app.main:app', host='127.0.0.1', port=8787)
