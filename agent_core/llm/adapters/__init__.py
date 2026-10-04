"""
Provider adapters behind the text gateway.

Each adapter does three things and nothing else: send one request in that provider's
native structured-output form, translate the provider's errors into `llm.errors`, and emit
one telemetry record per attempt. Choosing *which* provider to call is the gateway's job.
"""
