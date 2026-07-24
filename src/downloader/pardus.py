import os
import re
import hashlib
import sys
from html.parser import HTMLParser
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin
from urllib.request import Request, urlopen

from hash import HashMismatchError, SHA256Verifier


# This is the current official ISO mirror. Additional official mirrors can be
# supplied to PardusMirrorClient and are tried in order.
OFFICIAL_MIRRORS = ("https://indir.pardus.org.tr/ISO/",)
CHUNK_SIZE = 8 * 1024 * 1024
USER_AGENT = "pardus-usb-formatter/0.7"


def _log_error(message):
    print("Pardus downloader: {}".format(message), file=sys.stderr, flush=True)


class DownloadError(Exception):
    pass


class DownloadCancelled(DownloadError):
    pass


class CatalogError(DownloadError):
    pass


class ISOImage:
    def __init__(self, filename, desktop, url, sha256):
        self.filename = filename
        self.desktop = desktop
        self.url = url
        self.sha256 = sha256


class _DirectoryLinks(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links = []

    def handle_starttag(self, tag, attrs):
        if tag != "a":
            return
        href = dict(attrs).get("href")
        if href:
            self.links.append(href)


class PardusMirrorClient:
    """Discovers and downloads current GNOME/XFCE ISOs from Pardus mirrors."""

    def __init__(self, mirrors=None, timeout=30, opener=None):
        self.mirrors = tuple(mirrors or OFFICIAL_MIRRORS)
        self.timeout = timeout
        self._opener = opener or urlopen

    def discover_latest(self, cancel_event=None):
        errors = []
        for mirror_url in self.mirrors:
            self._raise_if_cancelled(cancel_event)
            try:
                return self._discover_from_mirror(mirror_url, cancel_event)
            except DownloadCancelled:
                raise
            except (CatalogError, HTTPError, URLError, OSError) as error:
                _log_error("Mirror lookup failed for {}: {}".format(mirror_url, error))
                errors.append("{}: {}".format(mirror_url, error))
        raise CatalogError("Unable to discover Pardus ISO images: {}".format("; ".join(errors)))

    def _discover_from_mirror(self, mirror_url, cancel_event):
        root_url = self._directory_url(mirror_url)
        root_links = self._directory_links(root_url, cancel_event)
        release_urls = []
        for link in root_links:
            release_name = link.rstrip("/")
            if re.match(r"^Pardus[0-9]+$", release_name):
                release_urls.append((self._release_key(release_name), urljoin(root_url, link)))
        if not release_urls:
            raise CatalogError("No Pardus release directories found at {}".format(root_url))

        _, release_url = max(release_urls, key=lambda item: item[0])
        release_url = self._directory_url(release_url)
        checksum_url = urljoin(release_url, "SHA256SUMS")
        checksums = self._parse_sha256s(self._fetch_text(checksum_url, cancel_event))
        images = self._latest_desktop_images(checksums, release_url)
        if len(images) != 2:
            raise CatalogError("Current Pardus release has no GNOME and XFCE SHA256SUMS entries")
        return images

    def download(self, image, target_path, progress=None, cancel_event=None):
        """Stream an ISO to target_path and atomically publish it after validation."""
        target_path = os.path.abspath(target_path)
        parent_dir = os.path.dirname(target_path)
        if not os.path.isdir(parent_dir):
            raise DownloadError("Destination directory does not exist: {}".format(parent_dir))
        part_path = target_path + ".part"
        completed = False
        written = 0
        try:
            self._raise_if_cancelled(cancel_event)
            self._remove_file(part_path)
            request = Request(image.url, headers={"User-Agent": USER_AGENT})
            with self._open(request) as response, open(part_path, "wb") as output:
                content_length = response.headers.get("Content-Length")
                total = int(content_length) if content_length and content_length.isdigit() else None
                verifier = SHA256Verifier(image.sha256)
                while True:
                    self._raise_if_cancelled(cancel_event)
                    chunk = response.read(CHUNK_SIZE)
                    if not chunk:
                        break
                    output.write(chunk)
                    verifier.update(chunk)
                    written += len(chunk)
                    if progress:
                        progress(written, total)
                output.flush()
                os.fsync(output.fileno())

            if total is not None and written != total:
                raise DownloadError("Download ended before all bytes were received")
            self._raise_if_cancelled(cancel_event)
            verifier.verify()
            os.replace(part_path, target_path)
            completed = True
            return target_path
        except HashMismatchError as error:
            _log_error(
                "SHA-256 mismatch for {}: expected {}, got {}".format(
                    image.filename, error.expected, error.actual
                )
            )
            raise
        except (HTTPError, URLError, OSError) as error:
            _log_error("Download failed for {}: {}".format(image.url, error))
            raise DownloadError("ISO download failed: {}".format(error))
        finally:
            if not completed:
                self._remove_file(part_path)

    def stage_local_file(self, source_path, target_path, progress=None, cancel_event=None):
        """Copy a local ISO to a temporary target while calculating its SHA-256."""
        written = 0
        source_path = os.path.abspath(source_path)
        target_path = os.path.abspath(target_path)
        parent_dir = os.path.dirname(target_path)
        part_path = target_path + ".part"
        completed = False
        try:
            if not os.path.isfile(source_path):
                raise DownloadError("ISO source file does not exist: {}".format(source_path))
            if not os.path.isdir(parent_dir):
                raise DownloadError("Destination directory does not exist: {}".format(parent_dir))
            self._raise_if_cancelled(cancel_event)
            self._remove_file(part_path)
            total = os.path.getsize(source_path)
            digest = hashlib.sha256()
            with open(source_path, "rb") as source, open(part_path, "wb") as output:
                while True:
                    self._raise_if_cancelled(cancel_event)
                    chunk = source.read(CHUNK_SIZE)
                    if not chunk:
                        break
                    output.write(chunk)
                    digest.update(chunk)
                    written += len(chunk)
                    if progress:
                        progress(written, total)
                output.flush()
                os.fsync(output.fileno())
            self._raise_if_cancelled(cancel_event)
            if written != total:
                raise DownloadError("Local ISO ended before all bytes were read")
            os.replace(part_path, target_path)
            completed = True
            return digest.hexdigest()
        except OSError as error:
            _log_error("Local ISO staging failed for {}: {}".format(source_path, error))
            raise DownloadError("Could not stage local ISO: {}".format(error))
        finally:
            if not completed:
                self._remove_file(part_path)

    def _directory_links(self, url, cancel_event):
        parser = _DirectoryLinks()
        parser.feed(self._fetch_text(url, cancel_event))
        return parser.links

    def _fetch_text(self, url, cancel_event):
        self._raise_if_cancelled(cancel_event)
        request = Request(url, headers={"User-Agent": USER_AGENT})
        with self._open(request) as response:
            content = response.read()
        self._raise_if_cancelled(cancel_event)
        return content.decode("utf-8", errors="replace")

    def _open(self, request):
        return self._opener(request, timeout=self.timeout)

    @staticmethod
    def _directory_url(url):
        return url if url.endswith("/") else url + "/"

    @staticmethod
    def _release_key(name):
        return tuple(int(part) for part in re.findall(r"[0-9]+", name))

    @staticmethod
    def _parse_sha256s(content):
        checksums = {}
        for line in content.splitlines():
            match = re.match(r"^([a-fA-F0-9]{64})\s+\*?(.+)$", line)
            if match:
                checksums[match.group(2).strip()] = match.group(1).lower()
        return checksums

    @staticmethod
    def _latest_desktop_images(checksums, release_url):
        # Checksum entries are the source of truth, so unlisted ISO files are
        # never offered even if a directory index contains them.
        candidates = {}
        pattern = re.compile(
            r"^Pardus-([0-9]+(?:\.[0-9]+)+)-(GNOME|XFCE)(?:-[^.]+)?-amd64\.iso$"
        )
        for filename, checksum in checksums.items():
            match = pattern.match(filename)
            if not match:
                continue
            version = tuple(int(part) for part in match.group(1).split("."))
            desktop = match.group(2)
            previous = candidates.get(desktop)
            if previous is None or version > previous[0]:
                candidates[desktop] = (version, ISOImage(
                    filename, desktop, urljoin(release_url, filename), checksum
                ))
        return [candidates[desktop][1] for desktop in ("GNOME", "XFCE") if desktop in candidates]

    @staticmethod
    def _raise_if_cancelled(cancel_event):
        if cancel_event is not None and cancel_event.is_set():
            raise DownloadCancelled("ISO download was cancelled")

    @staticmethod
    def _remove_file(path):
        try:
            os.unlink(path)
        except FileNotFoundError:
            pass
