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

**Not yet deployed to EKS.** Do not describe the live application as repaired yet.
A read-only migration preflight counted 59,943 existing items, no non-numeric legacy
product IDs, and no duplicate `(order_id, product_id)` positions at inspection time.
The V2 migration preserves the stored positions; it does NOT recover historical UUIDs
or prices. The original V1 migration is unchanged.

Deployment needs a controlled maintenance window:

1. Publish tested Orders and checkout images from the reviewed source revision.
2. Pause demo traffic and block new purchases; let in-flight requests finish.
3. Back up the disposable database if historical demo data must be retained. Do not
   restart its pod: the deployment uses ephemeral storage.
4. Stop old Orders writers before starting the new image and its Flyway migration.
   Old Orders code is incompatible with the new required position column; do not
   mix old/new versions or blindly roll back the image after migration.
5. Deploy the corrected checkout client, restore access, and rerun the independent
   purchase probe against EKS. Require the selected UUID and nonzero expected price
   to match the newly persisted order.
6. Resume traffic only after verification. For rollback, use a planned schema/database
   restore with matching old images, not an unreviewed automated image rollback.

Historical defective rows are retained as evidence; only new purchases can establish
a passing baseline after deployment. Fault injection and agent trials remain blocked
until then.
