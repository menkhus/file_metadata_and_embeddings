This patch modifies the `processing_stats` table in the SQLite database to include two new columns: `status` and `interrupted`.

- **`status TEXT DEFAULT 'completed'`**: This column will store the final status of a scan session. It defaults to 'completed' and will be explicitly set to 'interrupted' if the scan is stopped prematurely.

- **`interrupted BOOLEAN DEFAULT FALSE`**: This boolean flag provides a clear and queryable way to identify scans that did not run to completion.

These additions are the first step in ensuring that interrupted scans are no longer implicitly recorded as successful. By explicitly tracking the scan's outcome, we can build more reliable post-processing and reporting logic. The default values ensure backward compatibility with existing records.