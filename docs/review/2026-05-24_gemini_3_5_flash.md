# Code Review: SDH-ludusavi
**Date:** 2026-05-24
**Auditor Model:** Gemini 3.5 Flash

---

### 1. File Descriptor Reuse Race Condition on Cancelled Operations

* **[Severity]** High
* **File & Function/Line:** [main.py](file:///home/beallio/Dropbox/Scripts/SDH-ludusavi/main.py#L297-L384) in `_run_blocking`
* **Description:** 
  When a blocking task is cancelled, the `except asyncio.CancelledError:` block immediately triggers `remove_reader_if_active()` and closes the reader file descriptor with `close_fd(read_fd)`. However, if `read_completion_signal` was already scheduled in the event loop's ready queue before the cancellation handler completed, it will execute later.
  When `read_completion_signal` eventually runs, it attempts to close the same file descriptor integer `read_fd` again. If another thread or task opened a new socket, database connection, or file in the meantime, the operating system may have reused that file descriptor integer. Thus, the late execution of `close_fd` will unexpectedly close the unrelated new resource.
* **Vulnerable Code:**
  ```python
  def read_completion_signal() -> None:
      remove_reader_if_active()
      try:
          os.read(read_fd, 1)
      except OSError:
          pass
      close_fd(read_fd)
      with completion_lock:
          completed = completion
      if future.done() or completed is None:
          return
      kind, payload = completed
      if kind == "error":
          future.set_exception(payload)
          return
      future.set_result(payload)
  ```
  and
  ```python
      except asyncio.CancelledError:
          decky.logger.warning(
              "SDH-ludusavi operation was cancelled while worker may still be running"
          )
          remove_reader_if_active()
          close_fd(read_fd)
          future.cancel()
          raise
  ```
* **Proposed Fix:**
  Introduce a boolean flag `read_fd_closed` and a wrapper helper function `close_read_fd()` to ensure the reader file descriptor is only closed exactly once:
  ```python
  async def _run_blocking(callback: Any) -> Any:
      loop = asyncio.get_running_loop()
      future: asyncio.Future[Any] = loop.create_future()
      context = contextvars.copy_context()
      read_fd, write_fd = os.pipe()
      completion: tuple[str, Any] | None = None
      completion_lock = threading.Lock()
      reader_registered = False
      thread_started = False
      read_fd_closed = False

      def close_fd(fd: int) -> None:
          try:
              os.close(fd)
          except OSError:
              return

      def close_read_fd() -> None:
          nonlocal read_fd_closed
          if not read_fd_closed:
              read_fd_closed = True
              close_fd(read_fd)

      def remove_reader_if_active() -> None:
          if loop.is_closed() or not loop.is_running():
              return
          try:
              loop.remove_reader(read_fd)
          except (OSError, RuntimeError):
              return

      def read_completion_signal() -> None:
          remove_reader_if_active()
          try:
              os.read(read_fd, 1)
          except OSError:
              pass
          close_read_fd()
          with completion_lock:
              completed = completion
          if future.done() or completed is None:
              return
          kind, payload = completed
          if kind == "error":
              future.set_exception(payload)
              return
          future.set_result(payload)

      def worker() -> None:
          nonlocal completion
          try:
              result = context.run(callback)
          except BaseException as error:
              completed = ("error", error)
          else:
              completed = ("result", result)
          with completion_lock:
              completion = completed
          try:
              os.write(write_fd, b"x")
          except OSError:
              pass
          finally:
              close_fd(write_fd)

      try:
          loop.add_reader(read_fd, read_completion_signal)
          reader_registered = True
          thread = threading.Thread(target=worker, name="sdh-ludusavi-worker", daemon=True)
          thread.start()
          thread_started = True
      except BaseException:
          if reader_registered:
              remove_reader_if_active()
          close_read_fd()
          if not thread_started:
              close_fd(write_fd)
          future.cancel()
          raise

      try:
          return await asyncio.shield(future)
      except asyncio.CancelledError:
          decky.logger.warning(
              "SDH-ludusavi operation was cancelled while worker may still be running"
          )
          remove_reader_if_active()
          close_read_fd()
          future.cancel()
          raise
  ```

---

### 2. TypeError Crash from In-place Modification of Frozen Native Objects

* **[Severity]** High
* **File & Function/Line:** [src/index.tsx](file:///home/beallio/Dropbox/Scripts/SDH-ludusavi/src/index.tsx#L258-L299) in `normalizeAutoSyncStatusBrowserView` and `patchBrowserViewMethodAliases`
* **Description:** 
  The plugin attempts to patch property aliases (e.g. `raw.LoadURL = raw.loadURL`) directly onto the object returned by `CreateBrowserView` or `SteamClient.BrowserView.Create`. In modern Steam Client updates, native host-binding objects are frozen or non-extensible. Attempting to assign new properties to them throws a `TypeError: Cannot add property LoadURL, object is not extensible` which blocks the plugin's frontend initialization entirely.
* **Vulnerable Code:**
  ```typescript
  function patchBrowserViewMethodAliases(view: AutoSyncStatusBrowserViewOwner) {
    const raw = view as any;
    if (!raw.LoadURL && raw.loadURL) raw.LoadURL = raw.loadURL;
    if (!raw.SetBounds && raw.setBounds) raw.SetBounds = raw.setBounds;
    if (!raw.SetVisible && raw.setVisible) raw.SetVisible = raw.setVisible;
    if (!raw.SetFocus && raw.setFocus) raw.SetFocus = raw.setFocus;
    if (!raw.SetName && raw.setName) raw.SetName = raw.setName;
    if (!raw.SetWindowStackingOrder && raw.setWindowStackingOrder) {
      raw.SetWindowStackingOrder = raw.setWindowStackingOrder;
    }
    if (!raw.Destroy && raw.destroy) raw.Destroy = raw.destroy;
  }
  ```
* **Proposed Fix:**
  Remove `patchBrowserViewMethodAliases` and return a delegate adapter object instead of mutating the native SteamClient object in-place:
  ```typescript
  function normalizeAutoSyncStatusBrowserView(
    candidate: AutoSyncStatusBrowserViewOwner | null,
  ): AutoSyncStatusBrowserView | null {
    const candidates: Array<[string, AutoSyncStatusBrowserViewOwner | undefined | null]> = [
      ["root", candidate],
      ["m_browserView", candidate?.m_browserView],
      ["browserView", candidate?.browserView],
      ["BrowserView", candidate?.BrowserView],
      ["m_browserView.m_browserView", candidate?.m_browserView?.m_browserView],
    ];

    for (const [source, view] of candidates) {
      if (!view) {
        continue;
      }
      const raw = view as any;
      const hasLoad = typeof raw.LoadURL === "function" || typeof raw.loadURL === "function";
      const hasSetBounds = typeof raw.SetBounds === "function" || typeof raw.setBounds === "function";
      const hasSetVisible = typeof raw.SetVisible === "function" || typeof raw.setVisible === "function";

      if (hasLoad && hasSetBounds && hasSetVisible) {
        log("info", `BrowserView normalized from ${source}`, "autosync_status");
        return {
          LoadURL: (url: string) => {
            if (typeof raw.LoadURL === "function") raw.LoadURL(url);
            else if (typeof raw.loadURL === "function") raw.loadURL(url);
          },
          SetBounds: (x: number, y: number, w: number, h: number) => {
            if (typeof raw.SetBounds === "function") raw.SetBounds(x, y, w, h);
            else if (typeof raw.setBounds === "function") raw.setBounds(x, y, w, h);
          },
          SetVisible: (visible: boolean) => {
            if (typeof raw.SetVisible === "function") raw.SetVisible(visible);
            else if (typeof raw.setVisible === "function") raw.setVisible(visible);
          },
          SetFocus: (focus: boolean) => {
            const fn = raw.SetFocus ?? raw.setFocus;
            if (typeof fn === "function") fn.call(raw, focus);
          },
          SetName: (name: string) => {
            const fn = raw.SetName ?? raw.setName;
            if (typeof fn === "function") fn.call(raw, name);
          },
          SetWindowStackingOrder: (order: number) => {
            const fn = raw.SetWindowStackingOrder ?? raw.setWindowStackingOrder;
            if (typeof fn === "function") fn.call(raw, order);
          },
          Destroy: () => {
            const fn = raw.Destroy ?? raw.destroy;
            if (typeof fn === "function") fn.call(raw);
          }
        } as any;
      }
      log(
        "debug",
        `BrowserView candidate ${source} missing methods; keys=${objectKeys(view)} prototype=${getPrototypeKeys(view)}`,
        "autosync_status",
      );
    }

    return null;
  }
  ```

---

### 3. Blocking the Event Loop with Synchronous `/proc` Scans on Dismount

* **[Severity]** Medium
* **File & Function/Line:** [main.py](file:///home/beallio/Dropbox/Scripts/SDH-ludusavi/main.py#L214-L218) in `_unload`
* **Description:** 
  When the plugin unloads, the frontend dismount handler invokes `_unload` on the Python backend. This method synchronously calls `self._backend.stop()`, which triggers `self.resume_all_paused_processes()`. For every paused process, it runs a full, recursive process tree traversal by checking `/proc/<pid>/status` for all PIDs on the system. Doing this synchronously on the main thread blocks the async event loop and freezes the entire Decky UI.
* **Vulnerable Code:**
  ```python
      async def _unload(self) -> None:
          if self._backend is not None:
              self._backend.stop()
          decky.logger.info("SDH-ludusavi backend unloaded")
  ```
* **Proposed Fix:**
  Offload the backend `stop` process cleanup to a worker thread via the `_call` wrapper:
  ```python
      async def _unload(self) -> None:
          if self._backend is not None:
              await self._call("unload_stop", lambda: self._backend.stop())
          decky.logger.info("SDH-ludusavi backend unloaded")
  ```

---

### 4. Naive Datetime Modification Metadata Comparisons

* **[Severity]** Medium
* **File & Function/Line:** [py_modules/sdh_ludusavi/ludusavi.py](file:///home/beallio/Dropbox/Scripts/SDH-ludusavi/py_modules/sdh_ludusavi/ludusavi.py#L131-L166) in `get_conflict_metadata`
* **Description:** 
  The file modification time is captured using `datetime.fromtimestamp()`, yielding a naive datetime (ignoring the system's timezone offset). However, `backupModifiedAt` parsed from Ludusavi's backup payload is timezone-aware. Comparing these strings directly on the frontend or backend can lead to false-positives or false-negatives when determining recency.
* **Vulnerable Code:**
  ```python
              if mtimes:
                  metadata["localModifiedAt"] = datetime.fromtimestamp(max(mtimes)).isoformat()
  ```
* **Proposed Fix:**
  Use timezone-aware timestamps by calling `astimezone()`:
  ```python
              if mtimes:
                  metadata["localModifiedAt"] = datetime.fromtimestamp(max(mtimes)).astimezone().isoformat()
  ```

---

### 5. RecursionError Risk from Cycle-Building in Process Tree Parsing

* **[Severity]** Low
* **File & Function/Line:** [py_modules/sdh_ludusavi/service.py](file:///home/beallio/Dropbox/Scripts/SDH-ludusavi/py_modules/sdh_ludusavi/service.py#L1630-L1653) in `_process_tree`
* **Description:** 
  The recursion helper `visit` performs a depth-first search to compile a process hierarchy list from dynamic parent PIDs. If PIDs are rapidly recycled by the kernel while the process scanner is iterating, a transient parent-child dependency cycle could be constructed. An unresolved cycle will trigger a `RecursionError` and disrupt process suspension/resumption gates.
* **Vulnerable Code:**
  ```python
      ordered: list[int] = []

      def visit(target_pid: int) -> None:
          ordered.append(target_pid)
          for child_pid in sorted(children_by_parent.get(target_pid, [])):
              visit(child_pid)

      visit(pid)
      return ordered
  ```
* **Proposed Fix:**
  Keep track of visited PIDs to guarantee cycle detection:
  ```python
      ordered: list[int] = []
      visited: set[int] = set()

      def visit(target_pid: int) -> None:
          if target_pid in visited:
              return
          visited.add(target_pid)
          ordered.append(target_pid)
          for child_pid in sorted(children_by_parent.get(target_pid, [])):
              visit(child_pid)

      visit(pid)
      return ordered
  ```