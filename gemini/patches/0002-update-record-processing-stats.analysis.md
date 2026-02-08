This patch updates the `record_processing_stats` method to accept and store the new `interrupted` status.

- The method signature is changed from `record_processing_stats(self, session_id: str, stats: Dict[str, Any])` to `record_processing_stats(self, session_id: str, stats: Dict[str, Any], interrupted: bool = False)`. This adds an optional `interrupted` parameter that defaults to `False`.

- The `INSERT` statement is updated to populate the new `status` and `interrupted` columns. The `status` is set to 'interrupted' if the `interrupted` flag is `True`, and 'completed' otherwise. The `interrupted` column is set to the value of the `interrupted` flag.

This change allows the `scan_directory` method to explicitly tell the database whether the scan was interrupted, ensuring that the recorded statistics accurately reflect the state of the scan.