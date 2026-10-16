"""Один раз на своём Mac: получить SPOTIFY_REFRESH_TOKEN.

1. developer.spotify.com/dashboard → Create app. Redirect URI: http://127.0.0.1:8888/callback
   API: Web API. Скопируй Client ID и Client Secret.
2. В Терминале:  python3 scripts/spotify_auth.py CLIENT_ID CLIENT_SECRET
3. Откроется браузер → разреши доступ. В Терминале появится refresh token.
"""
import base64
import http.server
import json
import sys
import urllib.parse
import urllib.request
import webbrowser

REDIRECT = "http://127.0.0.1:8888/callback"
SCOPES = "playlist-modify-private playlist-modify-public playlist-read-private"

cid, secret = sys.argv[1], sys.argv[2]
code_box = {}


class H(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        code_box["code"] = q.get("code", [""])[0]
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write("Готово, вернись в Терминал.".encode())

    def log_message(self, *a):
        pass


url = "https://accounts.spotify.com/authorize?" + urllib.parse.urlencode(
    {"client_id": cid, "response_type": "code", "redirect_uri": REDIRECT, "scope": SCOPES})
print("Открываю браузер:", url)
webbrowser.open(url)
http.server.HTTPServer(("127.0.0.1", 8888), H).handle_request()

data = urllib.parse.urlencode({"grant_type": "authorization_code", "code": code_box["code"],
                               "redirect_uri": REDIRECT}).encode()
req = urllib.request.Request("https://accounts.spotify.com/api/token", data=data, headers={
    "Authorization": "Basic " + base64.b64encode(f"{cid}:{secret}".encode()).decode()})
tok = json.load(urllib.request.urlopen(req))
print("\nSPOTIFY_REFRESH_TOKEN =", tok["refresh_token"])
