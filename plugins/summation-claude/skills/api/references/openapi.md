# OpenAPI Reference

Fetch the live API contract from:

```text
{SUM_API_BASE_URL}/openapi.json
```

The contract should drive route selection. Prefer `operationId`, tags, summaries, parameter schemas, and response schemas over route-name guessing. **Literal `/v1/...` paths shown anywhere in these skills are illustrative and may move — resolve the live route from the contract; never depend on a hardcoded path.** If a documented path returns `404`, rediscover by operationId rather than assuming the resource is gone.

## Discovery Pattern

1. Fetch OpenAPI.
2. Search by product noun, for example `projects`, `tables`, `views`, `reports`, `query`, `chats`, `files`.
3. Call by `operationId` (`operation <operationId>`), which resolves the current path from the live spec — do not paste the literal path from a skill.
4. Read the operation schema before calling.
5. Supply only documented parameters and request body fields.
6. Preserve pagination and streaming semantics from the contract.

## Error Handling

Expect `application/problem+json` style error bodies where available. Preserve these fields in summaries:

- `type`
- `title`
- `status`
- `detail`
- `code`
- `request_id`

## Pagination

When list operations expose cursors, treat cursors as opaque. Do not construct or edit them manually.

## Idempotency

When a create, generate, import, or long-running operation documents idempotency support, send a unique idempotency key per user intent. Reusing the same key means replaying the same operation, not trying again as a fresh operation.

## Streaming

Streaming may be exposed as SSE or NDJSON. Preserve event ordering and terminal events. If a stream fails, summarize the last event type, request ID, and whether the terminal event was received.
