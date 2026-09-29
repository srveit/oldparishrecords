# Compatibility

| Era | Shape |
|-----|--------|
| v1.0 flat book | `parish_name`, `parish_place`, … on book JSON |
| v1.1 book | embedded `parish{ display_name, name, … }` on book |
| **v1.2 book** | `parish_id` only → separate **parish** JSON |
| Parish v1.0 | `opr-matricula-parish-meta` |

Adapter: map flat/embedded parish → write `examples/parish_*.json` once; books keep `parish_id`.

Canonical paths:
- `/workspace/lank-schema/book-meta/matricula_parish_meta.schema.json`
- `/workspace/lank-schema/book-meta/matricula_book_meta.schema.json`
