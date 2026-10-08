import AppKit
import WebKit

// The interface and database remain in the bundled local server; this shell owns its lifetime.
final class DesktopApp: NSObject, NSApplicationDelegate, WKNavigationDelegate, WKUIDelegate, WKScriptMessageHandler, WKDownloadDelegate {
    private var window: NSWindow!
    private var webView: WKWebView!
    private var server: Process?
    private var startupTimer: Timer?
    private var readyFile: URL?
    private var serverURL: URL?
    private var dataDirectory: URL!
    private var logFile: URL!
    private var logHandle: FileHandle?
    private var quitting = false
    private var downloads: [ObjectIdentifier: (WKDownload, URL, URL)] = [:]
    private let preferencesKey = "InterfacePreferences"

    func applicationDidFinishLaunching(_ notification: Notification) {
        buildMenu()
        buildWindow()
        do { try startServer() }
        catch { failStartup(error.localizedDescription) }
    }

    private func buildMenu() {
        let menu = NSMenu()
        let appMenu = NSMenu()
        appMenu.addItem(withTitle: "О программе OpenSociometry", action: #selector(NSApplication.orderFrontStandardAboutPanel(_:)), keyEquivalent: "")
        appMenu.addItem(.separator())
        appMenu.addItem(withTitle: "Открыть папку данных", action: #selector(openDataDirectory), keyEquivalent: "")
        appMenu.addItem(.separator())
        appMenu.addItem(withTitle: "Скрыть OpenSociometry", action: #selector(NSApplication.hide(_:)), keyEquivalent: "h")
        appMenu.addItem(.separator())
        appMenu.addItem(withTitle: "Завершить OpenSociometry", action: #selector(NSApplication.terminate(_:)), keyEquivalent: "q")
        let appItem = NSMenuItem(); appItem.submenu = appMenu; menu.addItem(appItem)
        let editMenu = NSMenu(title: "Правка")
        for (title, selector, key) in [("Отменить", "undo:", "z"), ("Вырезать", "cut:", "x"),
                                       ("Копировать", "copy:", "c"), ("Вставить", "paste:", "v"),
                                       ("Выделить всё", "selectAll:", "a")] {
            editMenu.addItem(withTitle: title, action: Selector(selector), keyEquivalent: key)
        }
        let editItem = NSMenuItem(); editItem.submenu = editMenu; menu.addItem(editItem)
        let fileMenu = NSMenu(title: "Файл")
        fileMenu.addItem(withTitle: "Печать / PDF…", action: #selector(printPage), keyEquivalent: "p")
        fileMenu.addItem(withTitle: "Закрыть окно", action: #selector(NSWindow.performClose(_:)), keyEquivalent: "w")
        let fileItem = NSMenuItem(); fileItem.submenu = fileMenu; menu.addItem(fileItem)
        let windowMenu = NSMenu(title: "Окно")
        windowMenu.addItem(withTitle: "Свернуть", action: #selector(NSWindow.performMiniaturize(_:)), keyEquivalent: "m")
        windowMenu.addItem(withTitle: "Масштаб", action: #selector(NSWindow.performZoom(_:)), keyEquivalent: "")
        let windowItem = NSMenuItem(); windowItem.submenu = windowMenu; menu.addItem(windowItem)
        NSApp.mainMenu = menu
        NSApp.windowsMenu = windowMenu
    }

    private func buildWindow() {
        let config = WKWebViewConfiguration()
        config.userContentController.add(self, name: "desktop")
        let preferences = UserDefaults.standard.dictionary(forKey: preferencesKey) as? [String: String] ?? [:]
        let raw = (try? JSONSerialization.data(withJSONObject: preferences)) ?? Data("{}".utf8)
        let json = String(data: raw, encoding: .utf8) ?? "{}"
        let bridge = #"""
        (() => {
          if (location.hostname !== '127.0.0.1') return;
          const send = message => window.webkit.messageHandlers.desktop.postMessage(message);
          const storage = window.localStorage;
          const saved = __PREFERENCES__;
          for (const [key, value] of Object.entries(saved)) storage.setItem(key, value);
          const set = Storage.prototype.setItem, remove = Storage.prototype.removeItem;
          Storage.prototype.setItem = function(key, value) {
            set.call(this, key, value);
            if (this === storage) send({type: 'preference', key: String(key), value: String(value)});
          };
          Storage.prototype.removeItem = function(key) {
            remove.call(this, key);
            if (this === storage) send({type: 'preference', key: String(key)});
          };
          window.print = () => send({type: 'print'});
          function exportAnchor(anchor) {
            if (!anchor.download || !/^(blob:|data:)/.test(anchor.href)) return false;
            const name = anchor.download;
            fetch(anchor.href).then(r => r.blob()).then(blob => {
              const reader = new FileReader();
              reader.onload = () => send({type: 'download', name, data: reader.result.split(',')[1]});
              reader.readAsDataURL(blob);
            }).catch(() => send({type: 'error', message: 'Не удалось подготовить файл для сохранения.'}));
            return true;
          }
          const click = HTMLAnchorElement.prototype.click;
          HTMLAnchorElement.prototype.click = function() {
            if (!exportAnchor(this)) click.call(this);
          };
          document.addEventListener('click', event => {
            const anchor = event.target.closest && event.target.closest('a[download]');
            if (anchor && exportAnchor(anchor)) event.preventDefault();
          }, true);
        })();
        """#.replacingOccurrences(of: "__PREFERENCES__", with: json)
        config.userContentController.addUserScript(WKUserScript(source: bridge, injectionTime: .atDocumentStart, forMainFrameOnly: true))
        webView = WKWebView(frame: .zero, configuration: config)
        webView.navigationDelegate = self
        webView.uiDelegate = self
        webView.allowsBackForwardNavigationGestures = true
        window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 1200, height: 820),
                          styleMask: [.titled, .closable, .miniaturizable, .resizable], backing: .buffered, defer: false)
        window.title = "OpenSociometry"
        window.isReleasedWhenClosed = false
        window.minSize = NSSize(width: 800, height: 580)
        window.setFrameAutosaveName("OpenSociometryMainWindow")
        window.contentView = webView
        window.center()
        window.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
        webView.loadHTMLString("<html><body style='font:18px -apple-system;padding:48px;color:#15181e'>Запуск OpenSociometry…</body></html>", baseURL: nil)
    }

    private func startServer() throws {
        let files = FileManager.default
        let support = try files.url(for: .applicationSupportDirectory, in: .userDomainMask, appropriateFor: nil, create: true)
        dataDirectory = support.appendingPathComponent("OpenSociometry", isDirectory: true)
        try files.createDirectory(at: dataDirectory, withIntermediateDirectories: true, attributes: [.posixPermissions: 0o700])
        logFile = dataDirectory.appendingPathComponent("server.log")
        try Data().write(to: logFile)
        logHandle = try FileHandle(forWritingTo: logFile)
        readyFile = files.temporaryDirectory.appendingPathComponent("opensociometry-\(UUID().uuidString).json")
        guard let resources = Bundle.main.resourceURL else {
            throw NSError(domain: "OpenSociometry", code: 1, userInfo: [NSLocalizedDescriptionKey: "Ресурсы приложения не найдены."])
        }
        let process = Process()
        process.executableURL = resources.appendingPathComponent("server/OpenSociometry")
        process.arguments = ["--no-browser"]
        var env = ProcessInfo.processInfo.environment
        env["SOCIOMETRY_DB"] = env["SOCIOMETRY_DB"] ?? dataDirectory.appendingPathComponent("sociometry.db").path
        env["SOCIOMETRY_PORT"] = "0"
        env["SOCIOMETRY_READY_FILE"] = readyFile!.path
        env["SOCIOMETRY_PARENT_PID"] = String(ProcessInfo.processInfo.processIdentifier)
        env["PYTHONUNBUFFERED"] = "1"
        process.environment = env
        process.standardOutput = logHandle
        process.standardError = logHandle
        process.terminationHandler = { [weak self] _ in
            DispatchQueue.main.async {
                guard let self = self, !self.quitting, self.serverURL != nil else { return }
                self.failStartup("Локальный сервер остановился. Закройте приложение и запустите его снова.")
            }
        }
        server = process
        try process.run()
        let deadline = Date().addingTimeInterval(45)
        startupTimer = Timer.scheduledTimer(withTimeInterval: 0.1, repeats: true) { [weak self] timer in
            guard let self = self, let ready = self.readyFile else { timer.invalidate(); return }
            if let raw = try? Data(contentsOf: ready),
               let info = try? JSONSerialization.jsonObject(with: raw) as? [String: Any],
               let address = info["url"] as? String, let url = URL(string: address),
               url.scheme == "http", url.host == "127.0.0.1", let port = url.port, port > 0 {
                timer.invalidate()
                try? files.removeItem(at: ready)
                self.serverURL = url
                self.webView.load(URLRequest(url: url))
            } else if !process.isRunning || Date() > deadline {
                timer.invalidate()
                self.failStartup("Не удалось запустить локальный сервер.")
            }
        }
    }

    private func failStartup(_ message: String) {
        startupTimer?.invalidate()
        let alert = NSAlert()
        alert.messageText = "OpenSociometry не удалось запустить"
        alert.informativeText = message + (logFile.map { "\n\nЖурнал: " + $0.path } ?? "")
        alert.addButton(withTitle: "Закрыть")
        alert.runModal()
        NSApp.terminate(nil)
    }

    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool { true }

    func applicationWillTerminate(_ notification: Notification) {
        quitting = true
        startupTimer?.invalidate()
        if let process = server, process.isRunning { process.terminate() }
        if let ready = readyFile { try? FileManager.default.removeItem(at: ready) }
        for (_, temporary, _) in downloads.values { try? FileManager.default.removeItem(at: temporary.deletingLastPathComponent()) }
        try? logHandle?.close()
        webView.configuration.userContentController.removeScriptMessageHandler(forName: "desktop")
    }

    @objc private func openDataDirectory() {
        if let directory = dataDirectory { NSWorkspace.shared.open(directory) }
    }

    @objc private func printPage() {
        let info = NSPrintInfo.shared.copy() as! NSPrintInfo
        info.horizontalPagination = .fit
        let operation = webView.printOperation(with: info)
        operation.showsPrintPanel = true
        operation.showsProgressPanel = true
        operation.runModal(for: window, delegate: nil, didRun: nil, contextInfo: nil)
    }

    private func showError(_ message: String) {
        let alert = NSAlert(); alert.messageText = "Не удалось выполнить действие"; alert.informativeText = message
        alert.beginSheetModal(for: window)
    }

    private func chooseDestination(_ name: String, completion: @escaping (URL?) -> Void) {
        let panel = NSSavePanel()
        panel.nameFieldStringValue = URL(fileURLWithPath: name).lastPathComponent
        panel.directoryURL = FileManager.default.urls(for: .downloadsDirectory, in: .userDomainMask).first
        panel.canCreateDirectories = true
        panel.beginSheetModal(for: window) { result in completion(result == .OK ? panel.url : nil) }
    }

    func userContentController(_ userContentController: WKUserContentController, didReceive message: WKScriptMessage) {
        guard message.frameInfo.isMainFrame, message.frameInfo.securityOrigin.host == "127.0.0.1",
              message.frameInfo.securityOrigin.port == serverURL?.port,
              let body = message.body as? [String: Any], let type = body["type"] as? String else { return }
        if type == "print" { printPage() }
        else if type == "preference", let key = body["key"] as? String {
            var preferences = UserDefaults.standard.dictionary(forKey: preferencesKey) as? [String: String] ?? [:]
            preferences[key] = body["value"] as? String
            UserDefaults.standard.set(preferences, forKey: preferencesKey)
        } else if type == "download", let name = body["name"] as? String,
                  let encoded = body["data"] as? String, let data = Data(base64Encoded: encoded) {
            chooseDestination(name) { [weak self] destination in
                guard let destination = destination else { return }
                do { try data.write(to: destination, options: .atomic) }
                catch { self?.showError(error.localizedDescription) }
            }
        } else if type == "error", let message = body["message"] as? String { showError(message) }
    }

    func webView(_ webView: WKWebView, decidePolicyFor action: WKNavigationAction, decisionHandler: @escaping (WKNavigationActionPolicy) -> Void) {
        guard let url = action.request.url else { decisionHandler(.cancel); return }
        if url.scheme == "about" { decisionHandler(.allow); return }
        if url.scheme == "http", url.host == serverURL?.host, url.port == serverURL?.port {
            if action.shouldPerformDownload { decisionHandler(.download) }
            else { decisionHandler(.allow) }
        } else if url.scheme == "blob" || url.scheme == "data" { decisionHandler(.download) }
        else {
            if ["https", "http", "mailto"].contains(url.scheme ?? "") { NSWorkspace.shared.open(url) }
            decisionHandler(.cancel)
        }
    }

    func webView(_ webView: WKWebView, decidePolicyFor response: WKNavigationResponse, decisionHandler: @escaping (WKNavigationResponsePolicy) -> Void) {
        let attachment = (response.response as? HTTPURLResponse)?.value(forHTTPHeaderField: "Content-Disposition")?.lowercased().contains("attachment") ?? false
        decisionHandler(attachment || !response.canShowMIMEType ? .download : .allow)
    }

    func webView(_ webView: WKWebView, navigationAction: WKNavigationAction, didBecome download: WKDownload) { download.delegate = self }
    func webView(_ webView: WKWebView, navigationResponse: WKNavigationResponse, didBecome download: WKDownload) { download.delegate = self }

    func download(_ download: WKDownload, decideDestinationUsing response: URLResponse, suggestedFilename: String, completionHandler: @escaping (URL?) -> Void) {
        chooseDestination(suggestedFilename) { [weak self] destination in
            guard let self = self, let destination = destination else { completionHandler(nil); return }
            do {
                let folder = FileManager.default.temporaryDirectory.appendingPathComponent("opensociometry-download-\(UUID().uuidString)")
                try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
                let temporary = folder.appendingPathComponent("download")
                self.downloads[ObjectIdentifier(download)] = (download, temporary, destination)
                completionHandler(temporary)
            } catch { self.showError(error.localizedDescription); completionHandler(nil) }
        }
    }

    func downloadDidFinish(_ download: WKDownload) {
        guard let (_, temporary, destination) = downloads.removeValue(forKey: ObjectIdentifier(download)) else { return }
        defer { try? FileManager.default.removeItem(at: temporary.deletingLastPathComponent()) }
        do {
            if FileManager.default.fileExists(atPath: destination.path) {
                _ = try FileManager.default.replaceItemAt(destination, withItemAt: temporary)
            } else { try FileManager.default.moveItem(at: temporary, to: destination) }
        } catch { showError(error.localizedDescription) }
    }

    func download(_ download: WKDownload, didFailWithError error: Error, resumeData: Data?) {
        if let (_, temporary, _) = downloads.removeValue(forKey: ObjectIdentifier(download)) {
            try? FileManager.default.removeItem(at: temporary.deletingLastPathComponent())
        }
        if (error as NSError).code != NSURLErrorCancelled { showError(error.localizedDescription) }
    }

    func webView(_ webView: WKWebView, runOpenPanelWith parameters: WKOpenPanelParameters, initiatedByFrame frame: WKFrameInfo, completionHandler: @escaping ([URL]?) -> Void) {
        let panel = NSOpenPanel()
        panel.allowsMultipleSelection = parameters.allowsMultipleSelection
        panel.canChooseDirectories = parameters.allowsDirectories
        panel.beginSheetModal(for: window) { result in completionHandler(result == .OK ? panel.urls : nil) }
    }

    func webView(_ webView: WKWebView, runJavaScriptAlertPanelWithMessage message: String, initiatedByFrame frame: WKFrameInfo, completionHandler: @escaping () -> Void) {
        let alert = NSAlert(); alert.messageText = "OpenSociometry"; alert.informativeText = message
        alert.beginSheetModal(for: window) { _ in completionHandler() }
    }

    func webView(_ webView: WKWebView, runJavaScriptConfirmPanelWithMessage message: String, initiatedByFrame frame: WKFrameInfo, completionHandler: @escaping (Bool) -> Void) {
        let alert = NSAlert(); alert.messageText = "OpenSociometry"; alert.informativeText = message
        alert.addButton(withTitle: "Да"); alert.addButton(withTitle: "Отмена")
        alert.beginSheetModal(for: window) { result in completionHandler(result == .alertFirstButtonReturn) }
    }

    func webView(_ webView: WKWebView, createWebViewWith configuration: WKWebViewConfiguration, for navigationAction: WKNavigationAction, windowFeatures: WKWindowFeatures) -> WKWebView? {
        if let url = navigationAction.request.url {
            if url.host == serverURL?.host && url.port == serverURL?.port { webView.load(navigationAction.request) }
            else if ["https", "http"].contains(url.scheme ?? "") { NSWorkspace.shared.open(url) }
        }
        return nil
    }
}

let application = NSApplication.shared
let delegate = DesktopApp()
application.delegate = delegate
application.setActivationPolicy(.regular)
application.run()
