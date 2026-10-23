"""Loopback-only OIDC fixture. Never imported by application code."""
import base64
import hashlib
import html
import json
import secrets
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlencode, urlsplit
import jwt
from cryptography.hazmat.primitives.asymmetric import rsa

ISSUER="http://localhost:9101/"
key=rsa.generate_private_key(public_exponent=65537,key_size=2048)
jwk=json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(key.public_key()))
jwk.update(kid="fixture-key",alg="RS256",use="sig")
transactions={}
codes={}
refreshes={}
verified=set()
refresh_count=0
verification_count=0

class Handler(BaseHTTPRequestHandler):
    def log_message(self,*args): pass
    def output(self,value,status=200,content_type="application/json"):
        body=value.encode() if isinstance(value,str) else json.dumps(value).encode()
        self.send_response(status); self.send_header("Content-Type",content_type); self.send_header("Content-Length",str(len(body))); self.end_headers(); self.wfile.write(body)
    def redirect(self,url):
        self.send_response(302); self.send_header("Location",url); self.end_headers()
    def do_GET(self):
        url=urlsplit(self.path)
        params={k:v[0] for k,v in parse_qs(url.query).items()}
        if url.path=="/.well-known/openid-configuration":
            return self.output({"issuer":ISSUER,"authorization_endpoint":ISSUER+"authorize","token_endpoint":ISSUER+"oauth/token","revocation_endpoint":ISSUER+"oauth/revoke","jwks_uri":ISSUER+"jwks","end_session_endpoint":ISSUER+"logout","response_types_supported":["code"],"subject_types_supported":["public"],"id_token_signing_alg_values_supported":["RS256"],"token_endpoint_auth_methods_supported":["client_secret_post","client_secret_basic"],"code_challenge_methods_supported":["S256"]})
        if url.path=="/jwks": return self.output({"keys":[jwk]})
        if url.path=="/stats": return self.output({"refreshes":refresh_count,"verificationEmails":verification_count})
        if url.path=="/authorize":
            if params.get("redirect_uri")!="http://127.0.0.1:3105/auth/callback": return self.output({},400)
            transaction=secrets.token_urlsafe(); transactions[transaction]=params
            return self.output('<h1>Test identity provider</h1><form method="post" action="/authorize"><input type="hidden" name="transaction" value="'+html.escape(transaction)+'"><label>Email<input name="email" type="email"></label><label>Password<input name="password" type="password"></label><button>Continue</button></form>',content_type="text/html")
        if url.path=="/logout": return self.redirect("http://127.0.0.1:3105/login")
        return self.output({},404)
    def do_POST(self):
        global refresh_count,verification_count
        raw=self.rfile.read(int(self.headers.get("Content-Length",0)))
        params=json.loads(raw) if "application/json" in self.headers.get("Content-Type","") else {k:v[0] for k,v in parse_qs(raw.decode()).items()}
        if self.path=="/api/v2/jobs/verification-email":
            if self.headers.get("Authorization")!="Bearer fixture-management-token": return self.output({},401)
            verification_count+=1; return self.output({"status":"pending"},202)
        if self.path=="/oauth/revoke":
            refreshes.pop(params.get("token"),None); return self.output({})
        if self.path=="/verify": verified.add(params["email"]); return self.output({"ok":True})
        if self.path=="/authorize":
            transaction=transactions.pop(params.get("transaction"),None)
            if not transaction or params.get("password")!="Test-password-123!": return self.output("Invalid credentials",401,"text/html")
            code=secrets.token_urlsafe(); codes[code]=(transaction,params["email"])
            return self.redirect(transaction["redirect_uri"]+"?"+urlencode({"code":code,"state":transaction["state"]}))
        if self.path=="/oauth/token":
            if params.get("grant_type")=="client_credentials":
                return self.output({"access_token":"fixture-management-token","token_type":"Bearer","expires_in":60})
            if params.get("grant_type")=="refresh_token":
                entry=refreshes.pop(params.get("refresh_token"),None)
                if not entry: return self.output({"error":"invalid_grant"},400)
                transaction,email=entry; refresh_count+=1; duration=300
            else:
                entry=codes.pop(params.get("code"),None)
                if not entry: return self.output({"error":"invalid_grant"},400)
                transaction,email=entry
                challenge=base64.urlsafe_b64encode(hashlib.sha256(params.get("code_verifier","").encode()).digest()).rstrip(b"=").decode()
                if challenge!=transaction.get("code_challenge"): return self.output({"error":"invalid_grant"},400)
                duration=2 if email.startswith("refresh") else 300
            now=int(time.time()); is_verified=not email.startswith("unverified") or email in verified
            sub="auth0|"+email
            common={"iss":ISSUER,"sub":sub,"iat":now,"exp":now+duration}
            profile={"email":email,"email_verified":is_verified,"name":"Test Teacher"}
            access={**common,"aud":"https://eduvia-api",**{"https://eduvia.app/claims/"+k:v for k,v in profile.items()}}
            identity={**common,"exp":now+300,"aud":"test-client","nonce":transaction.get("nonce"),"sid":email,**profile}
            refresh=secrets.token_urlsafe(); refreshes[refresh]=(transaction,email)
            return self.output({"access_token":jwt.encode(access,key,algorithm="RS256",headers={"kid":"fixture-key"}),"id_token":jwt.encode(identity,key,algorithm="RS256",headers={"kid":"fixture-key"}),"refresh_token":refresh,"expires_in":duration,"token_type":"Bearer","scope":"openid profile email offline_access"})
        return self.output({},404)

ThreadingHTTPServer(("127.0.0.1",9101),Handler).serve_forever()
