# Tool material requests

The craft supply pass reads the module event `need 1x Blacksmith Hammer (a tool, kept in the bank)` as a tool request. The reagent parser remains separate. The standing recipe and the family's craft/quest mode still authorize the existing hammer buyer; an old event cannot restore a cleared recipe or override a dungeon job.

The same buyer handles both standing craft requirements and their tool events. A missing reachable vendor produces the existing vendor-walk need. Arrival at a vendor permits a fresh purchase attempt, without repeating the original refusal every poll. An event is identified by its row ID and occurrence count. Its diagnostic outcome uses the existing persistent clock memo, restored on bridge startup. A new occurrence can report a new refusal. Memo persistence is asynchronous, so a crash before its write can repeat a diagnostic; it does not control purchase safety.

Each hammer insertion runs in a transaction that locks the requester's roster row and rechecks the recipe, current job, inventory including bank slots, and any identical pending, claimed or verifying town purchase. A completed purchase with the hammer already owned cannot buy another. A failed purchase can retry when no equivalent command remains active. Database errors roll back and propagate rather than marking the request handled. Other town purchases retain their existing policy.

`material request: ... item 5956 ... handled` reports a queued purchase, an existing pending purchase, or an already owned hammer. It does not prove a vendor purchase completed. After deployment, inspect that log alongside the command result and inventory before checking the live acceptance criterion.

Validation: `tests/test_tool_material_requests.py` exercises the real bridge event reader, buyer, and transaction writer with isolated database facts, including restart replay, vendor arrival, stale standing orders, ownership and rollback. No live craft orders are issued by these tests.
