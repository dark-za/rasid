-- إعداد قواعد بيانات "راصد" — يُنفَّذ مرة واحدة بحساب ذي صلاحيات (root)
-- استبدل كلمات المرور قبل التنفيذ، ولا ترفع الملف بعد وضع قيم حقيقية
--
-- ملاحظة MariaDB: حسابات المستخدمين المجهولين (user='') المتقدمة على '%'
-- تمنع اتصال rasid_app/rasid_reader محلياً بخطأ Access denied — انظّفها:
-- DROP USER IF EXISTS ''@'localhost';
-- DROP USER IF EXISTS ''@'%';

CREATE DATABASE IF NOT EXISTS `rasid_db`
  CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

-- مستخدم تطبيق راصد: قراءة وكتابة على جداول النظام فقط
-- (ALTER USER بعد الإنشاء لضمان تحديث السر عند إعادة التنفيذ)
CREATE USER IF NOT EXISTS 'rasid_app'@'%' IDENTIFIED BY 'CHANGE_ME_APP_PASSWORD';
ALTER USER 'rasid_app'@'%' IDENTIFIED BY 'CHANGE_ME_APP_PASSWORD';
GRANT SELECT, INSERT, UPDATE, DELETE, CREATE, INDEX, ALTER, REFERENCES
  ON `rasid_db`.* TO 'rasid_app'@'%';

-- مستخدم قراءة البصمة: SELECT فقط — لا يُمنح أي صلاحية كتابة
-- (يتطلب أن تكون جداول SmartPSS موجودة أصلاً؛ إن غابت فسيمنح عند إنشائها:
--  GRANT SELECT ON `smartpss_local`.* TO 'rasid_reader'@'%';)
CREATE USER IF NOT EXISTS 'rasid_reader'@'%' IDENTIFIED BY 'CHANGE_ME_READER_PASSWORD';
ALTER USER 'rasid_reader'@'%' IDENTIFIED BY 'CHANGE_ME_READER_PASSWORD';
GRANT SELECT ON `smartpss_local`.* TO 'rasid_reader'@'%';

FLUSH PRIVILEGES;
