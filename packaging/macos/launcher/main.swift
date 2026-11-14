// OpenScript for macOS: tiny native front end.
//
// A shell script cannot receive Finder "open document" events, so this
// launcher does it: it runs Contents/Resources/openscript.sh with the files
// it was asked to open (at launch, or later while OpenScript is running) and
// quits when the first run of the script (the whole Wine session) ends.
import Cocoa

final class AppDelegate: NSObject, NSApplicationDelegate {
    private var started = false
    private var pending: [String] = []

    func application(_ sender: NSApplication, openFiles filenames: [String]) {
        if started {
            run(filenames, quitWhenDone: false)   // engine already running
        } else {
            pending += filenames
        }
        sender.reply(toOpenOrPrint: .success)
    }

    func applicationDidFinishLaunching(_ notification: Notification) {
        // Give Finder a moment to deliver the files that launched us.
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.4) {
            self.started = true
            let args = CommandLine.arguments.dropFirst().filter { !$0.hasPrefix("-psn_") }
            self.run(self.pending + args, quitWhenDone: true)
        }
    }

    private func run(_ files: [String], quitWhenDone: Bool) {
        guard let script = Bundle.main.path(forResource: "openscript", ofType: "sh") else {
            NSApp.terminate(nil)
            return
        }
        let process = Process()
        process.executableURL = URL(fileURLWithPath: "/bin/bash")
        process.arguments = [script] + files
        // Screen scale (2 on Retina) so the script can pick the Windows DPI.
        // NSScreen.main is nil for this window-less launcher: use the
        // highest scale among the connected screens.
        var environment = ProcessInfo.processInfo.environment
        let scale = NSScreen.screens.map { $0.backingScaleFactor }.max() ?? 2
        environment["OPENSCRIPT_SCALE"] = String(Int(scale.rounded()))
        process.environment = environment
        if quitWhenDone {
            process.terminationHandler = { _ in
                DispatchQueue.main.async { NSApp.terminate(nil) }
            }
        }
        do {
            try process.run()
        } catch {
            if quitWhenDone { NSApp.terminate(nil) }
        }
    }
}

let app = NSApplication.shared
let delegate = AppDelegate()
app.delegate = delegate
// Wine shows its own windows; this front end stays out of the Dock.
app.setActivationPolicy(.accessory)
app.run()
