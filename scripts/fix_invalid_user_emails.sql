-- 修复 users 表中非法邮箱（如 zhangxw@szlab.ac.cn@example.com）
-- 用法：psql $DATABASE_URL -f scripts/fix_invalid_user_emails.sql
-- 或先设置 PGPASSWORD 等后：psql -h localhost -U postgres -d agenticworkflow -f scripts/fix_invalid_user_emails.sql

-- 将「含多个 @」的邮箱改为去掉末尾的 @example.com（得到真实邮箱），若冲突则改为 用户名_id@example.com
DO $$
DECLARE
  r RECORD;
  new_email TEXT;
  safe_local TEXT;
BEGIN
  FOR r IN
    SELECT id, username, email
    FROM users
    WHERE email ~ '@.*@'
       OR trim(email) = ''
       OR email ~ '\s'
       OR lower(email) LIKE '%.local'
  LOOP
    new_email := NULL;
    -- 若是 xxx@yyy@example.com，改为 xxx@yyy
    IF r.email IS NOT NULL AND trim(r.email) LIKE '%@example.com' AND (SELECT count(*) FROM regexp_matches(r.email, '@', 'g')) >= 2 THEN
      new_email := trim(regexp_replace(r.email, '@example\.com$', ''));
      IF new_email ~ '^[^@]+@[^@]+\.[^@]+$' THEN
        IF EXISTS (SELECT 1 FROM users WHERE email = new_email AND id != r.id) THEN
          new_email := NULL;
        END IF;
      ELSE
        new_email := NULL;
      END IF;
    END IF;
    IF new_email IS NULL THEN
      safe_local := coalesce(replace(replace(r.username, '@', '_'), ' ', '_'), 'user');
      new_email := safe_local || '+' || r.id::text || '@example.com';
    END IF;
    UPDATE users SET email = new_email, updated_at = NOW() WHERE id = r.id;
    RAISE NOTICE 'id=% username=% 旧邮箱=% -> %', r.id, r.username, r.email, new_email;
  END LOOP;
END $$;
