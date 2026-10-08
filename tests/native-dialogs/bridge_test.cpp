#include "relink_bridge.h"
#include <QApplication>
#include <QDir>
#include <QTemporaryDir>
#include <QTimer>
#include <QSet>
#include <QFileInfo>
#include <cstdio>

struct MsFolderEntry {
    std::int64_t id = -1;
    QString first;
    int flags = 0;
    QString second;
};
static_assert(sizeof(MsFolderEntry) == 32);
static_assert(offsetof(MsFolderEntry, first) == 8);
static_assert(offsetof(MsFolderEntry, second) == 24);
Q_DECLARE_METATYPE(MsFolderEntry)

class TestController : public QObject {
    Q_OBJECT
public:
    QPushButton *ok = nullptr;
    QString selected;
    int calls = 0;
    int mode = 0;
    QSet<QString> loaded {QStringLiteral("/")};
    QStringList listed;
signals:
    void NotifySelectionChanged(MsFolderEntry, MsFolderEntry);
public slots:
    void ListFolders(QString key) {
        listed.append(key);
        const QString path = key.mid(key.indexOf('/'));
        if (loaded.contains(QFileInfo(path).absolutePath()))
            loaded.insert(path);
    }
    void SelectFolder(QString folder) {
        ++calls;
        selected = folder;
        ok->setEnabled(mode != 2);
        if (mode == 3) {
            QTimer::singleShot(0, this, [this] { emit NotifySelectionChanged({}, {}); });
        } else if (mode != 1) {
            const QString path = folder.mid(folder.indexOf('/'));
            const bool invalid = mode == 4 || !loaded.contains(QFileInfo(path).absolutePath());
            emit NotifySelectionChanged({invalid ? -1 : 42,
                mode == 5 ? path + "/wrong" : path, 0, "sample"}, {});
        }
    }
};

int main(int argc, char **argv)
{
    QApplication app(argc, argv);
    QTemporaryDir temp;
    if (!temp.isValid())
        return 1;
    const QString folder = temp.path() + QStringLiteral("/Folder with spaces \u00f6");
    if (!QDir().mkdir(folder))
        return 1;
    int failures = 0;
    for (int scenario = 0; scenario < 12; ++scenario) {
        QDialog dialog;
        QPushButton ok(&dialog);
        ok.setEnabled(false);
        TestController controller;
        controller.ok = &ok;
        int clicks = 0;
        QObject::connect(&ok, &QPushButton::clicked, &dialog, [&] {
            ++clicks;
            if (scenario != 6)
                dialog.accept();
        });
        QString choice = folder + "/";
        if (scenario == 1) choice.clear();
        if (scenario == 2) choice = folder + "/missing";
        if (scenario == 3) { controller.mode = 1; ok.setEnabled(true); }
        if (scenario == 4) controller.mode = 2;
        if (scenario == 5) controller.mode = 3;
        if (scenario == 7) choice = "relative-folder";
        if (scenario == 8) controller.mode = 4;
        if (scenario == 9) controller.mode = 5;
        const QString prefix = scenario == 10 ? "" : scenario == 11 ? "bad:" : "1:002:";
        const int result = native_relink::finishChoice(&dialog, &controller, &ok, choice, {prefix});
        bool passed = result == (scenario == 0 ? QDialog::Accepted : QDialog::Rejected);
        passed = passed && clicks == ((scenario == 0 || scenario == 6) ? 1 : 0);
        passed = passed && !dialog.isVisible();
        if (scenario == 1 || scenario == 2 || scenario == 7 || scenario >= 10)
            passed = passed && controller.calls == 0;
        else
            passed = passed && controller.calls == 1 && controller.selected == prefix + folder;
        std::printf("scenario=%d %s\n", scenario, passed ? "PASS" : "FAIL");
        failures += !passed;
    }
    return failures != 0;
}

#include "bridge_test.moc"
