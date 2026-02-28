
from fastapi import FastAPI, HTTPException, Request, Path as FastAPIPath
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional, Dict, Any
import requests
import os
from datetime import datetime
import asyncio
from concurrent.futures import ThreadPoolExecutor


class SACRequest(BaseModel):
    method: str
    endpoint: str
    payload: Optional[Dict[str, Any]] = None


class SACClient:
    def __init__(self):
      
        self.base_url = os.getenv('SAC_BASE_URL', '').rstrip('/')
        self.token_url = os.getenv('SAC_TOKEN_URL', '')
        self.client_id = os.getenv('SAC_CLIENT_ID', '')
        self.client_secret = os.getenv('SAC_CLIENT_SECRET', '')
        
        if not all([self.base_url, self.token_url, self.client_id, self.client_secret]):
            raise ValueError("Missing SAC credentials")
        
        self.session = requests.Session()
        self.access_token = None
        self.token_expiry = 0
        self.csrf_token = None

    def _authenticate(self):
        if self.access_token and datetime.now().timestamp() < self.token_expiry:
            return self.access_token
        res = self.session.post(self.token_url, data={
            'grant_type': 'client_credentials',
            'client_id': self.client_id,
            'client_secret': self.client_secret
        })
        res.raise_for_status()
        data = res.json()
        self.access_token = data['access_token']
        self.token_expiry = datetime.now().timestamp() + data.get('expires_in', 3600) - 300
        return self.access_token

    def _fetch_csrf(self):
        headers = {
            'Authorization': f'Bearer {self._authenticate()}',
            'x-csrf-token': 'fetch',
            'x-sap-sac-custom-auth': 'true'
        }
        res = self.session.get(f"{self.base_url}/api/v1/csrf", headers=headers)
        res.raise_for_status()
        self.csrf_token = res.headers.get('x-csrf-token')
        return self.csrf_token

    def _sync_request(self, method, endpoint, payload=None):
        """Internal sync request - runs in thread pool"""
        
        url = f"{self.base_url}{endpoint}" if endpoint.startswith('/') else f"{self.base_url}/{endpoint}"
        headers = {
            'Authorization': f'Bearer {self._authenticate()}',
            'x-sap-sac-custom-auth': 'true',
            'Content-Type': 'application/json'
        }
        if method.upper() in ['POST', 'PUT', 'DELETE', 'PATCH']:
            headers['x-csrf-token'] = self.csrf_token or self._fetch_csrf()
        
        response = self.session.request(method.upper(), url, headers=headers, json=payload)
        
        # i dont know why but if i remove the refetching the csrf token it dosent do the post,put patvh calls and gives error 403 so for that case i handled this case
        if response.status_code == 403 and 'CSRF' in response.text.upper():
            headers['x-csrf-token'] = self._fetch_csrf()
            response = self.session.request(method.upper(), url, headers=headers, json=payload)
        return response

executor = ThreadPoolExecutor(max_workers=4)
app = FastAPI()

##after delpoying to certain domain i will chnahe the origin to tthat domain till that it will be set to all.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# r before the 3 colens is to convert html file into raw file.

#this HTML is AI generated based on on backend code
INDEX_HTML = r"""
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>SAC API Test Tool</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <style>
        body { font-family: system-ui, -apple-system, sans-serif; }
        .response-box { background: #1e1e1e; color: #d4d4d4; border-radius: 8px; padding: 1rem; font-family: monospace; white-space: pre-wrap; max-height: 400px; overflow-y: auto; }
        .loading { opacity: 0.6; pointer-events: none; }
    </style>
</head>
<body class="bg-gray-50 min-h-screen p-6">
    <div class="max-w-4xl mx-auto">
        <h1 class="text-2xl font-bold mb-6">SAC API Test Tool</h1>
        
        <div class="bg-white rounded-lg shadow p-6 mb-6">
            <div class="grid grid-cols-1 md:grid-cols-2 gap-4 mb-4">
                <div>
                    <label class="block text-sm font-medium mb-1">Method</label>
                    <select id="method" class="w-full border rounded px-3 py-2">
                        <option value="GET">GET</option>
                        <option value="POST">POST</option>
                        <option value="PUT">PUT</option>
                        <option value="DELETE">DELETE</option>
                        <option value="PATCH">PATCH</option>
                    </select>
                </div>
                <div>
                    <label class="block text-sm font-medium mb-1">Endpoint</label>
                    <input type="text" id="endpoint" placeholder="/api/v1/version" 
                           class="w-full border rounded px-3 py-2" value="/api/v1/version">
                </div>
            </div>
            
            <div class="mb-4">
                <label class="block text-sm font-medium mb-1">Payload (JSON, optional)</label>
                <textarea id="payload" rows="4" placeholder='{"key": "value"}' 
                          class="w-full border rounded px-3 py-2 font-mono text-sm"></textarea>
            </div>
            
            <button id="executeBtn" class="bg-blue-600 hover:bg-blue-700 text-white px-6 py-2 rounded font-medium">
                 Send Request
            </button>
        </div>

        <div id="responseSection" class="hidden">
            <h2 class="text-lg font-semibold mb-2">Response</h2>
            <div class="flex items-center gap-2 mb-2">
                <span id="statusBadge" class="px-2 py-1 rounded text-sm font-mono"></span>
                <span id="timingBadge" class="text-sm text-gray-500"></span>
            </div>
            <pre id="responseBody" class="response-box"></pre>
        </div>
    </div>

    <script>
        const executeBtn = document.getElementById('executeBtn');
        const responseSection = document.getElementById('responseSection');
        const statusBadge = document.getElementById('statusBadge');
        const timingBadge = document.getElementById('timingBadge');
        const responseBody = document.getElementById('responseBody');

        executeBtn.addEventListener('click', async () => {
            const method = document.getElementById('method').value;
            const endpoint = document.getElementById('endpoint').value;
            const payloadRaw = document.getElementById('payload').value;
            
            let payload = null;
            if (payloadRaw.trim()) {
                try { payload = JSON.parse(payloadRaw); }
                catch (e) { alert('Invalid JSON payload'); return; }
            }

            // UI loading state
            executeBtn.classList.add('loading');
            executeBtn.textContent = 'Executing...';
            responseSection.classList.add('hidden');

            const startTime = performance.now();
            
            try {
                const res = await fetch('/api/request', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ method, endpoint, payload })
                });
                
                const elapsed = ((performance.now() - startTime) / 1000).toFixed(2);
                const data = await res.json();
                
                // Show response
                responseSection.classList.remove('hidden');
                statusBadge.textContent = `Status: ${data.status_code}`;
                statusBadge.className = `px-2 py-1 rounded text-sm font-mono ${
                    data.status_code >= 200 && data.status_code < 300 ? 'bg-green-100 text-green-800' :
                    data.status_code >= 400 ? 'bg-red-100 text-red-800' : 'bg-yellow-100 text-yellow-800'
                }`;
                timingBadge.textContent = `${elapsed}s`;
                responseBody.textContent = typeof data.body === 'object' 
                    ? JSON.stringify(data.body, null, 2) 
                    : data.body;
                    
            } catch (err) {
                alert('Request failed: ' + err.message);
                console.error(err);
            } finally {
                executeBtn.classList.remove('loading');
                executeBtn.textContent = 'Send Request';
            }
        });
    </script>
</body>
</html>
"""


# all routes 
@app.get("/")
async def serve_ui():
    return HTMLResponse(content=INDEX_HTML)

@app.get("/{full_path:path}")
async def serve_spa(full_path: str):
    if full_path.startswith("api/"):
        raise HTTPException(status_code=404)
    return HTMLResponse(content=INDEX_HTML)

@app.post("/api/request")
async def execute_sac_request(req: SACRequest):
    try:
        client = SACClient()
        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(
            executor,
            client._sync_request,
            req.method,
            req.endpoint,
            req.payload
        )
        
        content_type = response.headers.get('Content-Type', '')
        if 'application/json' in content_type:
            try: body = response.json()
            except: body = response.text
        else:
            body = response.text
            
        return {
            "status_code": response.status_code,
            "body": body,
            "headers": dict(response.headers)
        }
    except requests.exceptions.Timeout:
        raise HTTPException(status_code=504, detail="SAC API timeout")
    except requests.exceptions.ConnectionError:
        raise HTTPException(status_code=502, detail="Cannot connect to SAC")
    except Exception as e:
        print(f"❌ Error: {str(e)}")
        raise HTTPException(status_code=500, detail=f"{type(e).__name__}: {str(e)}")

