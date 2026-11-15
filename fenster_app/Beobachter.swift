import Cocoa
import WebKit

final class Ablauf: NSObject, NSApplicationDelegate, WKNavigationDelegate {
    var fenster: NSWindow?

    func applicationDidFinishLaunching(_ mitteilung: Notification) {
        guard CommandLine.arguments.count > 1, let adresse = URL(string: CommandLine.arguments[1]) else {
            NSApp.terminate(nil)
            return
        }
        let rahmen = NSRect(x: 0, y: 0, width: 1120, height: 740)
        let fenster = NSWindow(
            contentRect: rahmen,
            styleMask: [.titled, .closable, .miniaturizable, .resizable],
            backing: .buffered,
            defer: false
        )
        fenster.title = "MarktRadar"
        fenster.appearance = NSAppearance(named: .darkAqua)
        fenster.backgroundColor = NSColor(srgbRed: 0.063, green: 0.075, blue: 0.063, alpha: 1)
        fenster.minSize = NSSize(width: 880, height: 620)
        fenster.titlebarAppearsTransparent = true
        let seite = WKWebView(frame: fenster.contentView?.bounds ?? rahmen)
        seite.navigationDelegate = self
        seite.autoresizingMask = [.width, .height]
        seite.setValue(false, forKey: "drawsBackground")
        fenster.contentView?.addSubview(seite)
        seite.load(URLRequest(url: adresse))
        fenster.center()
        fenster.makeKeyAndOrderFront(nil)
        self.fenster = fenster
        NSApp.activate(ignoringOtherApps: true)
    }

    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool {
        true
    }

    func webView(_ webView: WKWebView, didFinish navigation: WKNavigation!) {
        fputs("seite da\n", stderr)
    }

    func webView(_ webView: WKWebView, didFail navigation: WKNavigation!, withError error: Error) {
        fputs("laden fehlgeschlagen: \(error.localizedDescription)\n", stderr)
    }

    func webView(_ webView: WKWebView, didFailProvisionalNavigation navigation: WKNavigation!, withError error: Error) {
        fputs("start fehlgeschlagen: \(error.localizedDescription)\n", stderr)
    }
}

let app = NSApplication.shared
let ablauf = Ablauf()
app.setActivationPolicy(.regular)
app.delegate = ablauf
app.run()
