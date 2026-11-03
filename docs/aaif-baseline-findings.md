# AAIF baseline validation — 2026-11-03

## Result: storefront confirmation does not establish item correctness

No fault was injected. One authorized synthetic purchase was submitted through
`grot-gateway` in EKS context `grot-aws-test`, namespace `grot-aws-quick`, using a
temporary loopback port-forward. The forward was stopped after the check.
No deployments were changed or restarted.

Probe: `4beb802c34c3433994dde420b438e024`.
Order: `4c103f6e-a294-4b8d-b33d-dd5150444b04`.
Selected product: `cc789f85-1476-452a-8100-9e74502198e0`, quantity 1.

| Check | Observed |
|---|---|
| Storefront shopping stages and confirmation | Passed |
| Confirmed order ID exists in PostgreSQL | Yes |
| Unique probe email persisted with the order | Yes |
| Exactly one purchased item, quantity 1 | Yes |
| Persisted product matches selected UUID | **No: product_id is `0`** |
| Persisted unit cost | `0` (total_cost is `15`) |
| Independent single-probe outcome | **failed** |

Database checks ran as existing `db-o11y` monitoring identity, inside a READ ONLY
transaction. The probe confirmed it is not a superuser and has no order-table DML
privileges. Credentials stayed inside the database pod. A follow-up SELECT scoped
to this exact order confirmed the mismatched item; global order counts were not
used as proof of this purchase.

Raw probe evidence is saved locally at:
`~/Documents/Notes/Initiatives/grot-aaif-experiment/initial-purchase-probe.json`.

## Interpretation

This is an application baseline finding, **not an agent trial** and not evidence of
an agent falsely claiming recovery. It does demonstrate why confirmation HTML and
row existence alone are insufficient for the proposed verification criteria.

Do not relax the product-matching check just to get a green baseline. Diagnose the
UI → checkout → orders item mapping and compare deployed images with source.
Two root causes have now been reproduced and fixed locally:

1. `OrderEntity.items` used `@MappedCollection(keyColumn = "product_id")`.
   Spring Data JDBC writes the List index to that column, overwriting each product
   UUID. A database round-trip test reproduced UUIDs becoming `[0, 1]` before the fix.
   The mapping now uses a separate `item_position` column, introduced by Flyway V2.
2. Checkout passed its internal item objects directly to an inconsistent generated
   Orders serializer. It looked for `unitCost` on an object containing `price` and
   used the wrong wire-field name. A real-serializer HTTP-boundary test reproduced
   omitted prices. `HttpOrdersService` now explicitly maps `id` → `productId` and
   `price` → `unitCost`; the client model matches the Orders OpenAPI contract.

Read-only live diagnostics confirmed the correct UUID and price were still present
in checkout state after both checkout creation and shipping submission. The live
serializer also confirmed UUID preservation but omitted unit cost. These checks did
not submit another purchase or change deployment configuration.

The proposed numeric-SKU regression relies on receiving UUID product IDs. If the
current purchase path supplies `0`, numeric parsing might succeed. Therefore the
candidate fault is **not validated** until this baseline issue is understood and
corrected. Do not deploy the regression image yet.

## Reusable single-purchase probe

`scripts/verify_purchase.py` uses Python's standard library, a fresh cookie jar,
unique synthetic email, confirmation-page order ID, and exact DB item matching.
It requires explicit `--authorized-demo`, Kubernetes context, namespace and URL.
It creates one synthetic order; its database queries are read-only.

With the existing separate kubeconfig, AWS authentication, and a loopback storefront
port-forward already established:

```sh
python3 scripts/verify_purchase.py \
  --base-url http://127.0.0.1:18881 \
  --context grot-aws-test --namespace grot-aws-quick --authorized-demo
```

Outputs JSON and exits 0 for passed, 1 for failed, 2 for unknown. Network and database
infrastructure failures are unknown, not proof that a business transaction failed.
This is one probe, not the sustained multi-probe recovery window or final oracle.
The current confirmation parser requires the English `Order ID` label; a stable HTML
selector would remove that presentation dependency in a later small UI change.

Run offline tests:

```sh
python3 -m unittest discover -s tests -p test_verify_purchase.py
```

## Fix validation and deployment status

Local validation after fixes:

- Checkout: 5 tests pass, including the new multi-item serialization regression;
  TypeScript type-check passes.
- Orders: all 12 tests pass, including an actual HTTP → PostgreSQL → repository
  reload test in a disposable local PostgreSQL container, H2 round-trip regression,
  and V1 → V2 migration with 12 pre-existing items.
- Purchase verifier: 8 tests pass; persisted unit cost and total cost are now checked
  as well as product, quantity, order ID and email.
- `git diff --check` passes.

Docker Desktop was started for local tests. A temporary JDK 21 was downloaded under
`/tmp/grot-aaif-java` for Maven; no system Java installation was changed.

## Live fix verified — 2026-11-03 18:45 UTC

Deployed Orders and checkout images from source revision
`4e1693aa3b0cdb5dd6fa40eacb444ba7d575af47` after all PR checks and their image
publication jobs passed. Full publication workflow subsequently completed successfully.
Source: [PR #7](https://github.com/spslabo/grot-emporium/pull/7).

**This app is disposable. Prefer teardown/redeploy over preserving demo orders.**
At the user's direction, the actual rollout was:

1. Suspend the demo-traffic CronJob and delete its current job.
2. Uninstall only Helm release `grot`, removing the app and ephemeral PostgreSQL data.
   Preserve the runtime credential Secrets and separate Grafana/telemetry resources.
3. Reinstall `grot` with existing settings and the fixed Orders/checkout image tags.
   The fresh database applies V1 and V2 migrations. Other application images stay pinned
   to their prior revision.
4. Restart the gateway to resolve the recreated UI service address.
5. Complete three fresh storefront purchases, ten seconds apart, and verify each exact
   order, synthetic email, product UUID, quantity, unit cost and total in PostgreSQL.
6. Re-enable the demo-traffic CronJob. All nine deployments report 1/1 available.

All three independent checks **passed**:

| Order ID | Product UUID | Quantity | Unit / total cost |
|---|---|---|---|
| `3cb949a1-04fc-4ad3-8359-323bcac10e3a` | `cc789f85-1476-452a-8100-9e74502198e0` | 1 | 15 / 15 |
| `82715af5-26d2-4f11-9a7e-a0f0b1b32b96` | same | 1 | 15 / 15 |
| `fb00aff8-f91d-4ca3-9754-4e802bd14526` | same | 1 | 15 / 15 |

Evidence: `~/Documents/Notes/Initiatives/grot-aaif-experiment/rollout-4e1693a/purchase-after-{1,2,3}.json`.
These are application baseline checks, not agent experiment results.

Before the user clarified the disposable-data preference, an online database dump
and migration rehearsal were performed locally (60,000 rows, zero position mismatches).
That dump was NOT restored into the redeployed application. No ongoing backup system
was created. Do not repeat that preservation workflow for ordinary demo resets.

For consumers retaining an existing database, V2 remains available: it separates list
positions but cannot recover UUIDs or prices already overwritten by the old code.
Old Orders writers are incompatible with the new schema. The original V1 is unchanged.
The AAIF baseline is now passing; the candidate fault still needs its own reproducibility
test before agent trials.
