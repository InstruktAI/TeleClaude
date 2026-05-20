//! `WatchedFileWriter` — `std::io::Write` impl that cooperates with external
//! log rotation (logrotate, newsyslog, etc.) by reopening the underlying file
//! when its inode changes.
//!
//! Mirrors the Python `WatchedFileHandler` pattern: on each write, stat the
//! configured path; if the inode differs from the one we have open (or the
//! path no longer exists), close the current handle and open the path again.
//! This means logrotate can `mv app.log app.log.1` + `touch app.log` and the
//! next write lands in the fresh file with no daemon restart needed.
//!
//! The writer is wrapped by `tracing_appender::non_blocking` in `lib.rs` so
//! these syscalls happen on a background thread and never block the calling
//! thread. The stat-per-write overhead is acceptable on a non-blocking
//! background writer; the same pattern has been production-stable in the
//! Python `instrukt_ai_logging` library.

use std::fs::{File, OpenOptions};
use std::io;
use std::os::unix::fs::MetadataExt;
use std::path::PathBuf;

pub(crate) struct WatchedFileWriter {
    path: PathBuf,
    file: File,
    inode: u64,
}

impl WatchedFileWriter {
    pub(crate) fn open(path: PathBuf) -> io::Result<Self> {
        let file = OpenOptions::new().create(true).append(true).open(&path)?;
        let inode = file.metadata()?.ino();
        Ok(Self { path, file, inode })
    }

    /// If the path's inode no longer matches our open handle (logrotate
    /// moved/renamed/removed the file), close the stale handle and reopen
    /// the original path. Cheap when no rotation happened.
    fn reopen_if_rotated(&mut self) -> io::Result<()> {
        match std::fs::metadata(&self.path) {
            Ok(meta) if meta.ino() == self.inode => Ok(()),
            _ => {
                let file = OpenOptions::new().create(true).append(true).open(&self.path)?;
                self.inode = file.metadata()?.ino();
                self.file = file;
                Ok(())
            }
        }
    }
}

impl io::Write for WatchedFileWriter {
    fn write(&mut self, buf: &[u8]) -> io::Result<usize> {
        self.reopen_if_rotated()?;
        io::Write::write(&mut self.file, buf)
    }

    fn flush(&mut self) -> io::Result<()> {
        io::Write::flush(&mut self.file)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::io::Write;
    use tempfile::TempDir;

    #[test]
    fn writes_land_in_configured_path() {
        let tmp = TempDir::new().unwrap();
        let path = tmp.path().join("test.log");
        let mut w = WatchedFileWriter::open(path.clone()).unwrap();
        w.write_all(b"hello\n").unwrap();
        w.flush().unwrap();
        let contents = std::fs::read_to_string(&path).unwrap();
        assert_eq!(contents, "hello\n");
    }

    #[test]
    fn rotation_reopens_into_fresh_file() {
        let tmp = TempDir::new().unwrap();
        let path = tmp.path().join("rotate.log");

        // Write line 1 to original file.
        let mut w = WatchedFileWriter::open(path.clone()).unwrap();
        w.write_all(b"line1\n").unwrap();
        w.flush().unwrap();

        // External rotation: mv original out of the way, touch fresh file.
        std::fs::rename(&path, path.with_extension("log.1")).unwrap();
        std::fs::File::create(&path).unwrap();

        // Next write must land in the fresh file, not the rotated one.
        w.write_all(b"line2\n").unwrap();
        w.flush().unwrap();

        let rotated = std::fs::read_to_string(path.with_extension("log.1")).unwrap();
        let fresh = std::fs::read_to_string(&path).unwrap();
        assert_eq!(rotated, "line1\n");
        assert_eq!(fresh, "line2\n");
    }

    #[test]
    fn missing_path_after_unlink_is_recreated_on_next_write() {
        let tmp = TempDir::new().unwrap();
        let path = tmp.path().join("unlinked.log");

        let mut w = WatchedFileWriter::open(path.clone()).unwrap();
        w.write_all(b"before\n").unwrap();
        w.flush().unwrap();

        // External actor unlinks the file entirely (logrotate with delaycompress
        // missing, operator cleanup, etc.).
        std::fs::remove_file(&path).unwrap();

        // The reopen path uses create(true), so the next write recreates it.
        w.write_all(b"after\n").unwrap();
        w.flush().unwrap();

        let contents = std::fs::read_to_string(&path).unwrap();
        assert_eq!(contents, "after\n");
    }
}
