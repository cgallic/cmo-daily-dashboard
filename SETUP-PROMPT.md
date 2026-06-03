# Setup: point the dashboard at your own product

This repo ships with fictional **PingDesk** demo data. Here's how to wire it to
your own product, tracks, and channels.

## 1. Define your tracks and channels

A **track** is a generic grouping (a product, a brand, a client) — e.g.
`product_a`, `product_b`, `experimental`, or `demo-client`. A **channel** is a
distribution surface within a track — e.g. `youtube_product_a`,
`blog_seo_product_a`, `ads_paid_product_a`, `newsletter_product_a`.

Edit `fixtures/STATE.json` (or write directly to the store) so its `channels`
map reflects your real surfaces. Each channel needs a `status`, optional
`driver`, and an `evidence` string explaining the status.

## 2. Have your orchestrator write `items`

Your upstream "CMO loop" (whatever collects your analytics) writes suggestions
and tasks into the store. Use the Python API:

```python
from cmo_dashboard.store import InboxStore

store = InboxStore()                         # opens/creates inbox.db
rid = store.start_run(mode="dry-run")

store.add_item({
    "type": "suggestion",                    # 'suggestion' | 'task'
    "track": "product_a",                    # your generic grouping
    "channel": "blog_seo_product_a",
    "loop": "traffic_seo",                   # which loop emitted it
    "title": "Striking-distance keyword on page 2",
    "body": "Why this matters, in plain language.",
    "evidence": {"position": 12, "impressions_7d": 480},
    "score": 71,                             # 0-100 priority
    "owner": "OPERATOR-do",                  # AGENT-auto | OPERATOR-approve | OPERATOR-do
    "gate": "safe",                          # safe | irreversible
    # 'action' is DISPLAY-ONLY here — execution belongs to approval-inbox.
    "action": {"note": "Refresh intro + add 2 internal links."},
    "dedup_key": "2026-01-15:traffic_seo:blog_seo_product_a:striking-distance",
}, run_id=rid)

store.finish_run(rid, counts={"suggestions": 1})
store.export_jsonl(); store.export_state_json()
```

### Owner / column mapping

| owner | where it shows | meaning |
|-------|----------------|---------|
| `OPERATOR-approve` | left column ("Approve / Review") | needs a human decision |
| `OPERATOR-do` | right column ("Do today"), grouped by loop | a to-do for you |
| `AGENT-auto` | not shown in the two columns | auto-handled elsewhere |

Items with `state = "staged"` also surface in the left column.

## 3. Set channel health

```python
store.set_state(
    "blog_seo_product_a", status="consistent",
    track="product_a", driver="content_writer",
    evidence="40 posts live; 2 published this week",
)
```

Statuses: `consistent`, `running`, `intermittent`, `unverified`, `stalled`,
`no_driver`, `deprioritized`, `unknown`.

## 4. Rebuild and deploy

```bash
python -m cmo_dashboard.build      # regenerate dashboard/index.html
```

Then publish `dashboard/index.html` anywhere static, or wrap the build in a cron
/ CI job so the command center refreshes daily.

## 5. Customize labels (optional)

- Loop display names live in `LOOP_LABELS` in `cmo_dashboard/build.py`.
- Status → color mapping lives in `STATUS_COLOR` in the same file.

## Safety reminder

This dashboard is **read-only**. It surfaces what to look at; it does not act.
Keep execution (anything that touches a live system) in a separate
approval-inbox with its own guardrails.
