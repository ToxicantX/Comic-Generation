# Desktop Migration Baseline

Captured: 2026-09-28 (Asia/Shanghai)

This baseline is read-only. It records the current Docker-backed data source before any desktop data migration. It does not contain credentials, configuration values, or novel content.

## Source Runtime

- Git commit: `0fa6dc542c235ccc92f95c1d9322497b61269599`
- PostgreSQL: `16.14`
- Database size: `13,376,535` bytes
- PostgreSQL container: `comic-pipeline-postgres-runtime`
- PostgreSQL volume: `comic-pipeline_comic-pipeline-postgres-data`
- Console URL: `http://127.0.0.1:8199`

## Database Counts

| Table | Rows |
| --- | ---: |
| `comic_projects` | 8 |
| `comic_episodes` | 288 |
| `comic_chapters` | 288 |
| `comic_chapter_breakdowns` | 12 |
| `comic_setting_items` | 78 |
| `comic_visual_assets` | 31 |
| `comic_episode_approvals` | 8 |
| `comic_generated_outputs` | 15 |
| `comic_output_versions` | 52 |
| `comic_reviews` | 255 |
| `comic_jobs` | 126 |
| `comic_app_settings` | 0 |

## File Counts

| Source | Files | Bytes |
| --- | ---: | ---: |
| `novels/` | 11 | 9,234,031 |
| `manifests/` | 358 | 2,906,399 |
| `output/` | 104 | 71,880,263 |
| `workflows/` | 200 | 506,261 |

## Acceptance Rules

1. Create a PostgreSQL dump and a file manifest before writing to the desktop data directories.
2. Record SHA-256 and byte size for every backup artifact.
3. Restore into a separate target database and directory. Never overwrite this source in place.
4. Compare every table count above and report added, missing, or changed rows explicitly.
5. Compare source and target file counts, relative paths, byte sizes, and SHA-256 values.
6. Keep the current Docker volume available until the restored desktop runtime passes read-only health checks and one reversible sample workflow.

Counts are expected to change while the application remains in use. Capture a fresh baseline immediately before an authorized migration run.

## Isolated Restore Rehearsal

Completed on 2026-09-28 without replacing or clearing the Docker source database.

- Backup directory: `%APPDATA%/Comic Pipeline/backups/migration-20260928-231140`
- Custom dump: `1,075,077` bytes, SHA-256 `D79FB46F591DF140D78198E122599F07E8A0D1394D36EDE676566FC14DD2969B`
- Plain SQL dump: `5,677,509` bytes, SHA-256 `629549F4D223DA3FA00F28FBFE7F188C55B09889C22A123FDE6A4A453F803852`
- File payload: `673` files across novels, manifests, output, and workflows; source and backup counts, bytes, relative paths, and SHA-256 values matched.
- Restore target: isolated database `comic_pipeline_migration_20260928`
- Database reconciliation: `12` tables, `1,161` rows, zero count differences; the validation backend returned `8` projects.
- Source runtime after rehearsal: container `comic-pipeline-postgres-runtime` remained healthy with `RestartCount=0`.

This proves backup, restore, and reconciliation. It is not a production cutover: the desktop default database remains independently initialized until the user explicitly authorizes migration into it. The Docker volume remains the rollback source.
