"""User-facing launcher: opens the browser only when the server responds."""
import threading
import time
import urllib.request
import webbrowser

from app import PORT, app
import uvicorn


def open_when_ready():
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    for _ in range(60):
        try:
            with opener.open(f"http://127.0.0.1:{PORT}/api/state", timeout=1) as response:
                if response.status == 200:
                    webbrowser.open(f"http://127.0.0.1:{PORT}")
                    return
        except OSError:
            time.sleep(0.5)


if __name__ == '__main__':
    threading.Thread(target=open_when_ready, daemon=True).start()
    print(f"Tableau de bord : http://127.0.0.1:{PORT}", flush=True)
    uvicorn.run(app, host='127.0.0.1', port=PORT, access_log=False, log_level='warning')
