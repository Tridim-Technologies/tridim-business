# Public endpoint abuse controls

The platform applies application-level controls to login and the public Daraja STK callback. Counters are stored in the platform database as keyed HMAC digests; raw client IP addresses and login identities are not stored. The M-Pesa SDK remains stateless and does not persist attempts, callbacks, or rate-limit state.

## Defaults

| Setting | Default | Purpose |
| --- | ---: | --- |
| `LOGIN_MAX_REQUEST_BYTES` | 4096 | Maximum login request body |
| `LOGIN_ATTEMPTS_PER_IDENTITY_IP` | 10 | Attempts for a normalized username and client IP per window |
| `LOGIN_ATTEMPTS_PER_IP` | 300 | Aggregate login attempts per client IP per window |
| `LOGIN_ATTEMPT_WINDOW_SECONDS` | 900 | Login rate-limit window |
| `DARAJA_CALLBACK_MAX_BODY_BYTES` | 16384 | Maximum callback JSON body |
| `DARAJA_CALLBACK_REQUESTS_PER_IP` | 600 | Callback requests per client IP per window |
| `DARAJA_CALLBACK_RATE_WINDOW_SECONDS` | 60 | Callback request window |
| `DARAJA_UNKNOWN_CALLBACKS_PER_MINUTE` | 300 | New unmatched checkout IDs allowed per shared application window |
| `DARAJA_UNKNOWN_CALLBACK_RATE_WINDOW_SECONDS` | 60 | Unmatched callback creation window |
| `DARAJA_UNKNOWN_CALLBACK_RETENTION_SECONDS` | 300 | Lifetime for unmatched callback events before cleanup |
| `ENDPOINT_RATE_LIMIT_BUCKET_RETENTION_SECONDS` | 86400 | Maximum normal retention of counter rows |

All values must be positive integers. Login violations return HTTP 429 with `Retry-After`. Malformed/oversized callbacks and callback rate-limit violations receive the provider-compatible HTTP 200 acknowledgement and are dropped without creating a callback event. Callback bodies are capped before JSON parsing.

The unmatched-callback allowance is global across app instances sharing the database. Short-lived unmatched records preserve the initiation/callback race: an early callback can still be attached when the Daraja initiation response arrives. Events attached to a payment attempt are never removed by the cleanup command.

## Operations and deployment

Run the cleanup command at least every five minutes:

```sh
python manage.py cleanup_abuse_records
```

The command deletes expired rate-limit rows and unmatched Daraja callback events older than the configured retention. Scheduling is an operator responsibility; the application does not create a scheduler automatically. Until the command runs, old unmatched callbacks remain stored. The database needs routine backups, monitoring, and adequate write capacity because each limited request updates shared counters. The implementation works across instances sharing one transactional database; it does not require Redis or Kubernetes.

Client IP detection uses the socket peer (`REMOTE_ADDR`) and deliberately ignores caller-supplied `X-Forwarded-For`. When a reverse proxy is deployed, configure the proxy and web server so the application receives the actual client address in `REMOTE_ADDR`, strip/overwrite untrusted forwarding headers, and prevent direct public access to the application server. If multiple clients appear as one proxy address, IP-based quotas will aggregate for them.

Configure limits for expected traffic and monitor 429/drop rates. The fixed-window limiter is not a substitute for edge-level DDoS protection; use a trusted CDN/WAF or load-balancer request limit for volumetric traffic.
