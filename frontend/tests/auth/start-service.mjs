import { spawn } from "node:child_process";
import { resolve } from "node:path";
const service=process.argv[2];
const root=resolve("..");
const python=process.env.AUTH_TEST_PYTHON || resolve(root,"backend",process.platform==="win32"?".venv/Scripts/python.exe":".venv/bin/python");
let command=python, args=[], cwd=root;
const env={...process.env,PYTHONPATH:resolve(root,"backend"),APP_ENV:"test",DATABASE_URL:process.env.AUTH_E2E_DATABASE_URL||"postgresql+psycopg://eduvia_runtime:runtime_test_only@127.0.0.1:5434/eduvia_auth_test",AUTH_ISSUER:"http://localhost:9101/",AUTH_JWKS_URL:"http://localhost:9101/jwks",AUTH_AUDIENCE:"https://eduvia-api"};
if(service==="oidc") args=[resolve(root,"frontend/tests/auth/oidc.py")];
else if(service==="api") args=[resolve(root,"frontend/tests/auth/api.py")];
else {
 command=process.execPath; cwd=resolve(root,"frontend"); args=["node_modules/next/dist/bin/next","dev","--webpack","--hostname","127.0.0.1","--port","3105"];
 Object.assign(env,{AUTH_TEST_MODE:"1",APP_BASE_URL:"http://127.0.0.1:3105",API_INTERNAL_URL:"http://127.0.0.1:8005",AUTH0_DOMAIN:"http://localhost:9101",AUTH0_CLIENT_ID:"test-client",AUTH0_CLIENT_SECRET:"test-secret",AUTH0_MANAGEMENT_CLIENT_ID:"test-management",AUTH0_MANAGEMENT_CLIENT_SECRET:"test-management-secret",AUTH0_SECRET:"a".repeat(64),AUTH0_AUDIENCE:"https://eduvia-api",SESSION_REDIS_URL:process.env.AUTH_E2E_REDIS_URL||"redis://127.0.0.1:6381/2",SESSION_ENCRYPTION_KEY:"b".repeat(64)});
}
const child=spawn(command,args,{cwd,env,stdio:"inherit"});
for(const signal of ["SIGINT","SIGTERM"]) process.on(signal,()=>child.kill(signal));
child.on("exit",code=>process.exit(code||0));
