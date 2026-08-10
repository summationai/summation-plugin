---
name: validate
description: "Verify a Summation report against its sources before sharing. Use before external or executive distribution, or when the user asks if a report is solid."
---

# Summation Validate

MCP only. Validation can take a while — tell the user it’s running; don’t give up at ~2 minutes if still in progress.

## Flow

1. Resolve project and report (list tools / files if list_reports is empty).  
2. **`validate_report`**. Progress language while waiting.  
3. Verdict panel in plain language:  
   - How many claims checked / flagged  
   - Flagged items with why  
   - Overall: safe to share / share with caveats / fix first  

## Rules

- Never soften flags.  
- Don’t call a report valid if validation failed.  
- After `$addison-report`, offer this proactively.  
- No REST helper.
