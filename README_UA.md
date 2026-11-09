# ForPrint System Backup Manager

Постійний мініпроєкт для серверу `s01.forprint.net.ua` у `/opt/forprint-utils/system-backup-manager`.

Використання: `make inspect`, `make prepare`, `make backup`, `make verify`, `make check`.

- `prepare` — **безповоротне стирання** тільки після перевірки USB-транспорту, моделі/ємності HDD, RAID та ручного підтвердження. Один раз; **не запускай повторно** після першого резерву.
- `backup` — Debian bootable standalone clone (`MFS_CLONE`, ~70 GiB) + датовані файлові копії кореневої системи й `/srv/software_development` (`MFS_BACKUP`). Не форматує носій.
- `verify` перевіряє UUID, GRUB та завершені знімки, але **не доводить**, що HDD фізично завантажиться.
- Тільки **Legacy BIOS**, `md0` + `md1` RAID1; зовнішній HDD `WDC WD2500AAKS-00F0A0` 250 GB через USB, Development `/dev/sdd1`.
- Код, конфігурація та тести у Git; дампи, резервні копії, паролі й ключі у Git **не зберігаються**.

## Інсталяція з пакета (рекомендовано)

Перенеси ZIP у директорію staging, розпакуй так, щоб файл `install_once.sh` був поряд із `Makefile`, та виконай:

```bash
cd /path/to/unpacked/system-backup-manager
bash install_once.sh --publish
cd /opt/forprint-utils/system-backup-manager
make inspect
# Після перевірки фізичного диска й підтвердження втрати Windows-даних:
make prepare
make backup
make verify
```

`install_once.sh` не торкається HDD: лише копіює проєкт у `/opt`, запускає тести, робить локальний commit і пробує `git push` до GitHub. Якщо автентифікація GitHub відсутня, проєкт залишається встановленим; після налаштування авторизації виконай `cd /opt/forprint-utils/system-backup-manager && git push -u origin main`. Установник **не перезаписує** вже наявну директорію проєкту.

Для встановлення без GitHub використовуй `bash install_once.sh --install-only`.

Оновлення після першого успішного створення диска: `cd /opt/forprint-utils/system-backup-manager && make backup && make verify`.

`Makefile` завжди викликає Python CLI; ніяких прямих команд у чаті для форматування не потрібно. Запускай від root; зміни поточного `/etc/fstab`, RAID, Hestia, `/etc/sudoers.d/hestiaweb` не виконуються.

### Особливо важливо

Клон системи оновлюється **на місці**, тому під час оновлення не є транзакційним. Перерване копіювання може залишити клон тимчасово непридатним для завантаження. Датовані snapshots мають маркери успішності та `rsync --link-dest`, ротація до 10 завершених знімків кожного виду. За нестачі місця поточна операція зупиняється; старі завершені snapshots не видаляються.

Живі MySQL/MariaDB, containerd та інші БД не стають автоматично узгодженими від копіювання відкритих файлів. Для повної відновлюваності потрібен окремий узгоджений дамп і тест відновлення.

Дивись `docs/RECOVERY_UA.md` та `docs/SAFETY_UA.md`.
