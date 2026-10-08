#include <QApplication>
#include <QDialog>
#include <QStandardItemModel>
#include <QTimer>
#include <QTreeView>
#include <QVBoxLayout>
#include <cstdio>

int main(int argc, char **argv)
{
    QApplication app(argc, argv);
    QDialog dialog;
    dialog.setWindowTitle(QStringLiteral("Select Source Folder"));
    auto *layout = new QVBoxLayout(&dialog);
    auto *tree = new QTreeView(&dialog);
    auto *model = new QStandardItemModel(tree);
    auto *item = new QStandardItem(QStringLiteral("/tmp/test-media"));
    item->setData(QStringLiteral("/tmp/test-media"), Qt::UserRole);
    model->appendRow(item);
    tree->setModel(model);
    tree->setCurrentIndex(model->index(0, 0));
    layout->addWidget(tree);
    QTimer::singleShot(10, &dialog, &QDialog::reject);
    const int result = dialog.exec();
    dialog.show();
    QTimer::singleShot(650, &app, &QApplication::quit);
    app.exec();
    std::printf("result=%d rows=%d selection=%d\n", result, model->rowCount(), tree->currentIndex().isValid());
    return result != QDialog::Rejected || model->rowCount() != 1 ||
           tree->currentIndex() != model->index(0, 0) ||
           item->data(Qt::UserRole).toString() != QStringLiteral("/tmp/test-media");
}
