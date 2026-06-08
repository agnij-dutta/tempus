# wend-agent

Ephemeral container that runs Claude Code against a freshly cloned GitHub repo and streams SSE in the Mac daemon's wire format. Lives behind Tempus's `/v1/cloud-dispatch` proxy.

## Env contract

| Var | Required | Default | Notes |
|---|---|---|---|
| `WEND_AGENT_ID` | yes (in prod) | `dev-agent` | UUID minted by the FastAPI provisioner |
| `WEND_REPO` | yes | empty | `owner/name` |
| `WEND_REPO_REF` | no | `main` | branch, tag, or SHA |
| `WEND_GITHUB_INSTALL_TOKEN` | yes | empty | GitHub App installation token, scoped read |
| `WEND_ANTHROPIC_API_KEY` | yes | empty | injected by ECS `secrets` from SSM |
| `WEND_IDLE_TIMEOUT_SEC` | no | `900` | matches the mobile UI session idle window |
| `WEND_LISTEN_PORT` | no | `8080` | the cloudflared tunnel binds here |
| `WEND_NO_TUNNEL` | no | unset | truthy skips cloudflared, for local smoke tests |
| `WEND_DDB_TABLE` | no | empty | `wend-agents` table; tunnel URL written here when ready |

## Local smoke test

```bash
WEND_NO_TUNNEL=1 \
WEND_REPO=octocat/Hello-World \
WEND_ANTHROPIC_API_KEY=sk-... \
python3 entrypoint.py
```

Then in another shell:

```bash
curl -N -X POST http://127.0.0.1:8080/v1/dispatch \
  -H 'Content-Type: application/json' \
  -d '{"prompt":"list the files in this repo"}'
```

The response is `text/event-stream` with `event: route`, JSONL frames, `event: stderr`, and a final `event: done` matching the Mac daemon's wire format.

## Build

```bash
./build.sh                                # local dev image
AWS_ACCOUNT_ID=… AWS_REGION=ap-south-1 ./build.sh    # push to ECR
```

## SSE protocol

Mirrors `mac-daemon/Sources/WendDaemonCore/Server.swift` byte-for-byte. The mobile app's `useDispatch` parser cannot tell whether it is talking to a Mac daemon or a wend-agent container.
