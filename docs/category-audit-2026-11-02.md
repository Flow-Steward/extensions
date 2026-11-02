# Published extension taxonomy audit — 2026-11-02

Scope: all 35 releases listed at catalog commit `554c51977e5deb96e78a70a6c1e2a296beb72af0`. Reviewed the exact tagged manifest, declared host contracts and operations, and release documentation. This is a metadata audit, not a new live-service test.

## Findings and rules

- Eleven release-specific category corrections. Other 24 category mappings remain unchanged. Existing category ids suffice; no new taxonomy or Core change.
- WordPress & WooCommerce is both CMS and E-commerce, with implemented inventory and sales operations.
- Shopify is E-commerce, Inventory and Sales. Its 33 published operations do not implement CMS pages, blogs or articles. The vendor platform being a CMS is insufficient to advertise a CMS connector.
- IMAP and SMTP are Email and Messaging. Workspace exposes Gmail, Drive and Sheets, so Productivity, Email, Documents and Data apply.
- Docling belongs to Documents and Data. Image Processing belongs to Media and AI because background removal runs U2-NetP; its resize operation is interpolation, not generative enhancement.
- Qdrant, Pinecone, Neo4j and PostgreSQL/pgvector are Data and AI because their published operations implement vector retrieval. They do not register a language model provider.
- TypeSafe AI (JEV) already has AI. Choice/Score/Noul evaluation is an action integration, not the Flow Steward model-provider contract. Keep `tool, action`.
- Only Ollama and OpenRouter among these 35 releases declare `llm_provider`, and both have the matching provider contract. Eight SQL connectors declare `dataset_connector` and have matching dataset contracts. A read/search operation alone does not make a dataset connector or a host resource query.
- All 35 catalog capability lists equal their tagged manifest `features`; permission lists equal declared `required_scopes`. This verifies declaration parity only; it does not establish that every database read operation is integrated with Dataset or saved Data Query. Administrative UI queries do not by themselves change an extension profile.
- Notification and ingress profiles remain on SMTP/Telegram/WhatsApp as declared. No database triggers added. Qdrant and Showcase retain `artifact_bundle`; an operation reading/writing an artifact does not imply shipping a bundle.
- Existing tags and descriptions were inspected for the affected function boundaries and retained; categories are explicit, not inferred from tags. Discogs marketplace statistics and collection/wantlist operations remain Media, without claiming shop/order management.

## All published releases

Primary category is first. Source links point to the exact reviewed tag. Capabilities are unchanged runtime feature ids.

| Extension / source | Version | Reviewed categories | Capabilities |
| --- | --- | --- | --- |
| [Airtable](https://github.com/Flow-Steward/ext-data-airtable/blob/v1.0.1/extension.yaml) | 1.0.1 | data | tool, action |
| [BigQuery](https://github.com/Flow-Steward/ext-data-bigquery/blob/v1.0.1/extension.yaml) | 1.0.1 | data | tool, action |
| [ClickHouse](https://github.com/Flow-Steward/ext-data-clickhouse/blob/v1.3.1/extension.yaml) | 1.3.1 | data | tool, dataset_connector, action, query |
| [Discogs API](https://github.com/Flow-Steward/ext-discogs/blob/v0.2.1/extension.yaml) | 0.2.1 | media | tool, action, query |
| [Docling Document Extraction](https://github.com/Flow-Steward/ext-document-docling/blob/v0.3.0/extension.yaml) | 0.3.0 | documents, data | tool, action |
| [Example Showcase Extension](https://github.com/Flow-Steward/ext-example-showcase/blob/v1.2.1/extension.yaml) | 1.2.1 | developer-tools | tool, action, query, workflow_trigger, artifact_bundle |
| [File Transfer](https://github.com/Flow-Steward/ext-file-transfer-sftp/blob/v0.3.1/extension.yaml) | 0.3.1 | data | tool, action |
| [Firestore](https://github.com/Flow-Steward/ext-data-firestore/blob/v1.0.2/extension.yaml) | 1.0.2 | data | tool, action |
| [Generic IMAP Mailbox](https://github.com/Flow-Steward/ext-email-imap/blob/v0.2.1/extension.yaml) | 0.2.1 | email, messaging | tool, action |
| [Google Workspace](https://github.com/Flow-Steward/ext-google-workspace/blob/v0.3.1/extension.yaml) | 0.3.1 | productivity, email, documents, data | tool, action |
| [Image Processing](https://github.com/Flow-Steward/ext-image-processing/blob/v0.2.1/extension.yaml) | 0.2.1 | media, ai | tool, action |
| [Microsoft SQL Server](https://github.com/Flow-Steward/ext-data-mssql/blob/v1.3.1/extension.yaml) | 1.3.1 | data | tool, dataset_connector, action, query |
| [MongoDB](https://github.com/Flow-Steward/ext-data-mongodb/blob/v1.0.2/extension.yaml) | 1.0.2 | data | tool, action |
| [MySQL & MariaDB](https://github.com/Flow-Steward/ext-data-mysql/blob/v1.3.1/extension.yaml) | 1.3.1 | data | tool, dataset_connector, action, query |
| [Neo4j](https://github.com/Flow-Steward/ext-graph-neo4j/blob/v1.0.2/extension.yaml) | 1.0.2 | data, ai | tool, action |
| [OceanBase](https://github.com/Flow-Steward/ext-data-oceanbase/blob/v1.3.1/extension.yaml) | 1.3.1 | data | tool, dataset_connector, action, query |
| [Ollama LLM Provider](https://github.com/Flow-Steward/ext-llm-ollama/blob/v1.2.1/extension.yaml) | 1.2.1 | ai | tool, llm_provider |
| [OpenRouter LLM Provider](https://github.com/Flow-Steward/ext-llm-openrouter/blob/v1.2.1/extension.yaml) | 1.2.1 | ai | tool, llm_provider |
| [Oracle](https://github.com/Flow-Steward/ext-data-oracle/blob/v1.0.1/extension.yaml) | 1.0.1 | data | tool, action |
| [Outgoing Email](https://github.com/Flow-Steward/ext-email-smtp/blob/v0.3.1/extension.yaml) | 0.3.1 | email, messaging | notify, action |
| [Pinecone Vector Database](https://github.com/Flow-Steward/ext-vector-pinecone/blob/v1.0.1/extension.yaml) | 1.0.1 | data, ai | tool, action |
| [PostgreSQL](https://github.com/Flow-Steward/ext-data-postgres/blob/v1.4.0/extension.yaml) | 1.4.0 | data, ai | tool, dataset_connector, action, query |
| [Qdrant Vector Store](https://github.com/Flow-Steward/ext-vector-qdrant/blob/v1.0.1/extension.yaml) | 1.0.1 | data, ai | tool, action, artifact_bundle |
| [Redis](https://github.com/Flow-Steward/ext-data-redis/blob/v1.0.1/extension.yaml) | 1.0.1 | data | tool, action |
| [Shopify](https://github.com/Flow-Steward/ext-ecommerce-shopify/blob/v0.5.1/extension.yaml) | 0.5.1 | ecommerce, inventory, sales | tool, action |
| [SingleStore](https://github.com/Flow-Steward/ext-data-singlestore/blob/v1.3.1/extension.yaml) | 1.3.1 | data | tool, dataset_connector, action, query |
| [Snowflake](https://github.com/Flow-Steward/ext-data-snowflake/blob/v1.3.1/extension.yaml) | 1.3.1 | data | tool, dataset_connector, action, query |
| [Spanner](https://github.com/Flow-Steward/ext-data-spanner/blob/v1.3.1/extension.yaml) | 1.3.1 | data | tool, dataset_connector, action, query |
| [SQLite](https://github.com/Flow-Steward/ext-data-sqlite/blob/v1.0.1/extension.yaml) | 1.0.1 | data | tool, action |
| [Supabase](https://github.com/Flow-Steward/ext-data-supabase/blob/v1.0.1/extension.yaml) | 1.0.1 | data | tool, action |
| [Telegram Notifications](https://github.com/Flow-Steward/ext-messaging-telegram/blob/v1.3.0/extension.yaml) | 1.3.0 | messaging | notify, action, ingress_event |
| [TypeSafe AI (JEV)](https://github.com/Flow-Steward/ext-typesafe-ai/blob/v1.0.3/extension.yaml) | 1.0.3 | ai | tool, action |
| [Valkey](https://github.com/Flow-Steward/ext-data-valkey/blob/v1.0.1/extension.yaml) | 1.0.1 | data | tool, action |
| [WhatsApp](https://github.com/Flow-Steward/ext-messaging-whatsapp/blob/v0.1.0/extension.yaml) | 0.1.0 | messaging | notify, action, ingress_event |
| [WordPress & WooCommerce](https://github.com/Flow-Steward/ext-cms-wordpress-woocommerce/blob/v1.2.1/extension.yaml) | 1.2.1 | cms, ecommerce, inventory, sales | tool, action |

## Publication and future releases

`category_overrides.json` binds these corrections to exact repository/tag URLs. It is intentionally separate from immutable release records, capabilities and permissions. The normal generator applies it during every scheduled render. A different release or repository does not inherit an old correction. New releases should declare `listing.categories` themselves; the existing `listing.category` stays primary. New published functionality must be reviewed before updating a correction.

Archives, per-architecture targets, hashes, sizes, permissions, source links, icons and all historical records stay unchanged. Only the generated category arrays and catalog revision need change.

## SQL Dataset follow-up

The functional follow-up distinguishes ordinary workflow reads from actual Dataset integration. The initial declaration check missed that Oracle, BigQuery and SQLite had workflow reads without Dataset support. This is not fixed by adding catalog flags alone.

Oracle and BigQuery receive real Dataset registry declarations, connection/schema actions, validation, preview, saved query execution and output inference in Oracle 1.1.0 and BigQuery 1.1.1. Existing native workflow writes remain separate; Dataset operations are read-only. Their supported saved SQL grammar is intentionally conservative and documented in each repository. Source and both architecture archives are validated before catalog publication.

SQLite was withdrawn from the catalog at the owner's request after the candidate's review found that Core's administrative calls omit the trusted account/project scope required for project-scoped file access. Its registration and release history records were removed from the current catalog, including deprecated listings; the dated table above records the earlier audit snapshot. Reintroduction requires a separately approved working integration. MongoDB and the other native non-SQL integrations likewise remain workflow operations pending a suitable Core contract.

The archive checker now refuses an explicit Dataset Connector registry without its matching public `dataset_connector` feature. This catches the declaration mismatch before a new release enters the marketplace. It does not replace runtime integration tests.
