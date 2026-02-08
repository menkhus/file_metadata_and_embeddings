This patch modifies the `scan_directory` method to handle `KeyboardInterrupt` (Ctrl+C) gracefully.

- **Catching `KeyboardInterrupt`**: The `except (KeyboardInterrupt, SystemExit)` block is modified. Instead of re-raising the exception, it now sets `self.interrupt_handler.shutdown_requested = True`. This prevents the program from exiting immediately and allows it to proceed to the final statistics recording step.

- **Recording Interruption Status**: The call to `self.db_manager.record_processing_stats` is updated to pass the `interrupted` status: `self.db_manager.record_processing_stats(session_id, processing_stats, interrupted=self.interrupt_handler.should_shutdown())`. This ensures that if the scan was interrupted, the database record will accurately reflect that.

With this change, when you interrupt the scan, the program will stop processing new files, and then it will save the final statistics, correctly marking the session as 'interrupted'. This makes the data in the `processing_stats` table reliable and prevents incomplete scans from being misinterpreted as successful.