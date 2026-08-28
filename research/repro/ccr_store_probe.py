import json, urllib.request
# unique fingerprint so we can find it in the DB
items=[f"ZQX7-UNIQUE-TOKEN-{i:04d}" for i in range(1,61)]
body={"model":"claude-sonnet-4-5-20250929","max_tokens":64,
  "messages":[{"role":"user","content":"list them"},
    {"role":"assistant","content":[{"type":"tool_use","id":"tu1","name":"q","input":{}}]},
    {"role":"user","content":[{"type":"tool_result","tool_use_id":"tu1","content":json.dumps(items)},
                              {"type":"text","text":"how many?"}]}]}
req=urllib.request.Request("http://127.0.0.1:8792/v1/messages",data=json.dumps(body).encode(),
    headers={"Content-Type":"application/json","x-api-key":"t","anthropic-version":"2023-06-01"})
urllib.request.urlopen(req,timeout=90).read()
print("sent 60 unique-token strings")
