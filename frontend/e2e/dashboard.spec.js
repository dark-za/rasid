import { expect, test } from '@playwright/test';

const sampleAttendance = {
  date: '2026-10-24',
  total_records_processed: 1,
  logs: [{
    employee_id: '16',
    employee_name: 'سالم',
    check_time: '2026-10-24 08:20:00',
    device: 'بوابة 1',
    state: 0,
  }],
  late_employees: [{
    employee_id: '16',
    employee_name: 'سالم',
    arrival_time: '2026-10-24 08:20:00',
    late_minutes: 5,
    shift_date: '2026-10-24',
    shift_name: 'صباحية',
  }],
};

const sampleReport = {
  from_date: '2026-10-01',
  to_date: '2026-10-24',
  shift_name: 'صباحية',
  shift_start: '08:00',
  grace_period_minutes: 15,
  total_late_days: 1,
  total_late_minutes: 5,
  employees: [{
    employee_id: '16',
    employee_name: 'سالم',
    late_days: 1,
    total_late_minutes: 5,
    average_late_minutes: 5,
  }],
};

async function mockApi(page, options = {}) {
  const state = {
    attendanceSearch: null,
    attendanceRequests: 0,
    authenticatedRequests: 0,
    publicRequests: 0,
    loginRequests: 0,
    loginServiceFailure: Boolean(options.loginServiceFailure),
    attendanceFailure: Boolean(options.attendanceFailure),
    branchConflict: Boolean(options.branchConflict),
    holdAttendance: Boolean(options.holdInitialAttendance),
    reportSearch: null,
    databaseTest: null,
    databaseUpdate: null,
    employeeSyncRequests: 0,
    branchTransfer: null,
    shiftCreate: null,
    shiftUpdate: null,
    shiftAssignment: null,
    shiftDelete: null,
    pendingAttendanceResolvers: [],
    employees: [
      { employee_id: '16', name: 'سالم', active: true },
      { employee_id: '17', name: 'منى', active: true },
    ],
    shifts: [
      {
        id: 1,
        name: 'صباحية',
        start_time: '08:00',
        end_time: '17:00',
        grace_period_minutes: 15,
        lateness_mode: 'after_grace',
        color: '#2563EB',
        is_active: true,
      },
      {
        id: 2,
        name: 'مسائية',
        start_time: '22:00',
        end_time: '06:00',
        grace_period_minutes: 10,
        lateness_mode: 'from_start',
        color: '#7C3AED',
        is_active: false,
      },
    ],
    assignments: [{
      id: 1,
      employee_id: '16',
      shift_id: 1,
      start_date: '2020-01-01',
      end_date: null,
      shift_name: 'صباحية',
    }],
    branchRecords: [{
      id: 1,
      employee_id: '16',
      employee_name: 'سالم',
      branch_name: 'فرع النخيل',
      start_date: '2026-01-01',
      end_date: null,
      notes: null,
      is_current: true,
      is_future: false,
    }],
    databaseSettings: {
      host: '192.168.8.3',
      port: 3306,
      attendance_database: 'smartpss_local',
      attendance_username: 'rasid_reader',
      attendance_password_set: true,
    },
  };
  state.releaseAttendance = () => {
    state.pendingAttendanceResolvers.splice(0).forEach(resolve => resolve());
  };

  await page.route('**/api/**', async route => {
    const request = route.request();
    const url = new URL(request.url());
    const { pathname, searchParams } = url;
    const method = request.method();

    if (pathname === '/api/auth/login' && method === 'POST') {
      state.loginRequests += 1;
      if (state.loginServiceFailure) {
        return route.fulfill({ status: 500, body: 'Internal Server Error' });
      }
      const credentials = request.postDataJSON();
      if (credentials.username !== 'admin' || credentials.password !== 'test-password') {
        return route.fulfill({ status: 401, json: { detail: 'بيانات تسجيل الدخول غير صحيحة' } });
      }
      return route.fulfill({
        json: { access_token: 'test-session-token', token_type: 'bearer', expires_in: 28800 },
      });
    }

    if (method !== 'GET' && !request.headers().authorization) {
      return route.fulfill({ status: 401, json: { detail: 'سجّل الدخول للمتابعة' } });
    }
    if (request.headers().authorization) state.authenticatedRequests += 1;
    else state.publicRequests += 1;

    if (pathname === '/api/admin/database' && method === 'GET') {
      return route.fulfill({ json: state.databaseSettings });
    }

    if (pathname === '/api/admin/database/test' && method === 'POST') {
      state.databaseTest = request.postDataJSON();
      return route.fulfill({
        json: { attendance_connected: true, ready: true },
      });
    }

    if (pathname === '/api/admin/database' && method === 'PUT') {
      state.databaseUpdate = request.postDataJSON();
      return route.fulfill({
        json: { status: 'saved', message: 'تم اختبار اتصال قاعدة البصمة وحفظ إعداداتها وتطبيقها. لم تُعرض كلمة المرور.', settings: state.databaseSettings },
      });
    }

    if (pathname === '/api/attendance/today' && method === 'GET') {
      state.attendanceRequests += 1;
      if (state.holdAttendance) {
        await new Promise(resolve => state.pendingAttendanceResolvers.push(resolve));
      }
      if (state.attendanceFailure) {
        return route.fulfill({
          status: 503,
          json: { detail: 'خدمة الحضور غير متاحة' },
        });
      }
      return route.fulfill({ json: sampleAttendance });
    }

    if (pathname === '/api/attendance' && method === 'GET') {
      state.attendanceSearch = {
        date: searchParams.get('date'),
        employee_id: searchParams.get('employee_id'),
      };
      return route.fulfill({
        json: { ...sampleAttendance, date: state.attendanceSearch.date },
      });
    }

    if (pathname === '/api/reports/late' && method === 'GET') {
      state.reportSearch = {
        from: searchParams.get('from'),
        to: searchParams.get('to'),
      };
      return route.fulfill({
        json: {
          ...sampleReport,
          from_date: state.reportSearch.from || sampleReport.from_date,
          to_date: state.reportSearch.to || sampleReport.to_date,
        },
      });
    }

    if (pathname === '/api/shifts' && method === 'GET') {
      return route.fulfill({ json: state.shifts });
    }

    if (pathname === '/api/shifts' && method === 'POST') {
      state.shiftCreate = request.postDataJSON();
      const created = { id: 3, ...state.shiftCreate };
      state.shifts.push(created);
      return route.fulfill({ status: 201, json: created });
    }

    if (pathname.startsWith('/api/shifts/') && method === 'PUT') {
      const shiftId = Number(pathname.split('/').at(-1));
      const changes = request.postDataJSON();
      state.shiftUpdate = { id: shiftId, ...changes };
      state.shifts = state.shifts.map(shift => ({
        ...shift,
        ...(shift.id === shiftId ? changes : {}),
        ...(changes.is_active ? { is_active: shift.id === shiftId } : {}),
      }));
      return route.fulfill({ json: state.shifts.find(shift => shift.id === shiftId) });
    }

    if (pathname.startsWith('/api/shifts/') && method === 'DELETE') {
      state.shiftDelete = Number(pathname.split('/').at(-1));
      state.shifts = state.shifts.filter(shift => shift.id !== state.shiftDelete);
      return route.fulfill({ json: { status: 'success' } });
    }

    if (pathname === '/api/employees' && method === 'GET') {
      return route.fulfill({ json: state.employees });
    }

    if (pathname === '/api/employees/sync' && method === 'POST') {
      state.employeeSyncRequests += 1;
      return route.fulfill({ json: { created: 1, updated: 1, total: 2 } });
    }

    if (pathname === '/api/employees' && method === 'POST') {
      const created = request.postDataJSON();
      state.employees.push({ ...created, active: true });
      return route.fulfill({ status: 201, json: state.employees.at(-1) });
    }

    if (pathname === '/api/employee-shifts' && method === 'GET') {
      return route.fulfill({ json: state.assignments });
    }

    if (pathname === '/api/employee-shifts' && method === 'POST') {
      state.shiftAssignment = request.postDataJSON();
      const shift = state.shifts.find(item => item.id === state.shiftAssignment.shift_id);
      const created = {
        id: state.assignments.length + 1,
        ...state.shiftAssignment,
        end_date: null,
        shift_name: shift?.name,
      };
      state.assignments.push(created);
      return route.fulfill({ status: 201, json: created });
    }

    if (pathname === '/api/employee-branches' && method === 'GET') {
      return route.fulfill({
        json: {
          items: state.branchRecords,
          total: state.branchRecords.length,
          limit: 200,
          offset: 0,
        },
      });
    }

    if (pathname === '/api/employee-branches' && method === 'POST') {
      state.branchTransfer = request.postDataJSON();
      if (state.branchConflict) {
        return route.fulfill({
          status: 409,
          json: { detail: 'تاريخ النقل يتداخل مع سجل فرع سابق' },
        });
      }
      const created = {
        id: state.branchRecords.length + 1,
        ...state.branchTransfer,
        end_date: null,
        is_current: false,
        is_future: true,
      };
      state.branchRecords.push(created);
      return route.fulfill({ status: 201, json: created });
    }

    return route.fulfill({
      status: 404,
      json: { detail: `واجهة API غير مهيأة للاختبار: ${method} ${pathname}` },
    });
  });

  return state;
}

async function openDashboard(page, options) {
  const state = await mockApi(page, options);
  await page.goto('/');
  await expect(page.getByRole('heading', { name: 'راصد | لوحة متابعة الحضور' })).toBeVisible();
  await expect(page.getByText('بوابة 1')).toBeVisible();
  await expect(page.getByRole('button', { name: 'إضافة وردية' })).toHaveCount(0);
  expect(state.publicRequests).toBeGreaterThan(0);
  return state;
}

async function signIn(page) {
  await page.getByLabel('اسم المستخدم').fill('admin');
  await page.getByLabel('كلمة المرور').fill('test-password');
  await page.getByRole('button', { name: 'تسجيل الدخول' }).click();
}

async function openAdminPanel(page) {
  await page.getByRole('button', { name: 'دخول المشرف' }).click();
  await signIn(page);
  await expect(page.getByRole('heading', { name: 'راصد | لوحة المشرف' })).toBeVisible();
  await expect(page.getByLabel('عنوان خادم قاعدة البصمة')).toHaveValue('192.168.8.3');
}

test('loads the public dashboard without login and requires admin login for management', async ({ page }) => {
  const state = await mockApi(page);
  await page.goto('/');

  await expect(page.getByRole('heading', { name: 'راصد | لوحة متابعة الحضور' })).toBeVisible();
  await expect(page.getByText('بوابة 1')).toBeVisible();
  await page.getByRole('button', { name: 'دخول المشرف' }).click();
  await expect(page.getByRole('heading', { name: 'دخول المشرف' })).toBeVisible();
  await page.getByLabel('اسم المستخدم').fill('wrong-user');
  await page.getByLabel('كلمة المرور').fill('wrong-password');
  await page.getByRole('button', { name: 'تسجيل الدخول' }).click();

  await expect(page.getByRole('alert')).toContainText('بيانات تسجيل الدخول غير صحيحة');
  expect(state.authenticatedRequests).toBe(0);
  expect(state.publicRequests).toBeGreaterThan(0);
  expect(state.loginRequests).toBe(1);
});

test('explains when the login backend is unavailable', async ({ page }) => {
  await mockApi(page, { loginServiceFailure: true });
  await page.goto('/');
  await page.getByRole('button', { name: 'دخول المشرف' }).click();
  await page.getByLabel('اسم المستخدم').fill('admin');
  await page.getByLabel('كلمة المرور').fill('test-password');
  await page.getByRole('button', { name: 'تسجيل الدخول' }).click();

  await expect(page.getByRole('alert')).toContainText('خدمة تسجيل الدخول غير متاحة الآن (رمز 500)');
});

test('logs out of the admin panel and returns to the public dashboard', async ({ page }) => {
  const state = await openDashboard(page);
  await openAdminPanel(page);

  await page.getByRole('button', { name: 'تسجيل الخروج' }).click();

  await expect(page.getByRole('heading', { name: 'راصد | لوحة متابعة الحضور' })).toBeVisible();
  await expect(page.getByRole('button', { name: 'دخول المشرف' })).toBeVisible();
  expect(state.publicRequests).toBeGreaterThan(0);
});

test('tests and saves only attendance database settings without exposing stored passwords', async ({ page }) => {
  const state = await openDashboard(page);
  await openAdminPanel(page);
  const dbSection = page.getByRole('heading', { name: 'اتصال قاعدة البصمة' })
    .locator('..').locator('..').locator('..');

  await expect(dbSection.getByLabel('كلمة مرور قاعدة راصد')).toHaveCount(0);
  await expect(dbSection.getByLabel('اسم قاعدة راصد')).toHaveCount(0);
  await dbSection.getByLabel('عنوان خادم قاعدة البصمة').fill('192.168.8.9');
  await dbSection.getByRole('button', { name: 'اختبار الاتصال' }).click();

  await expect.poll(() => state.databaseTest).toMatchObject({
    host: '192.168.8.9',
    attendance_database: 'smartpss_local',
    attendance_username: 'rasid_reader',
  });
  await expect(state.databaseTest).not.toHaveProperty('app_database');
  await expect(state.databaseTest).not.toHaveProperty('app_password');
  await expect(dbSection.getByText('قاعدة البصمة: متصلة')).toBeVisible();
  await dbSection.getByRole('button', { name: 'حفظ وتطبيق الإعدادات' }).click();
  await expect.poll(() => state.databaseUpdate?.host).toBe('192.168.8.9');
  await expect(state.databaseUpdate).not.toHaveProperty('app_database');
  await expect(page.getByText('تم اختبار اتصال قاعدة البصمة وحفظ إعداداتها وتطبيقها. لم تُعرض كلمة المرور.', { exact: true })).toBeVisible();
});

test('automatically loads mocked attendance, employee roster, assignments, and branch history', async ({ page }) => {
  await openDashboard(page);

  const storedCredentials = await page.evaluate(() => ({
    local: localStorage.length,
    session: sessionStorage.length,
  }));
  expect(storedCredentials).toEqual({ local: 0, session: 0 });
  await expect(page.getByRole('row').filter({ hasText: 'سالم' }).getByText('صباحية').first()).toBeVisible();
  await expect(page.getByRole('row').filter({ hasText: 'منى' }).getByText('غير معيّن')).toBeVisible();
  await expect(page.getByText('فرع النخيل')).toBeVisible();
  await expect(page.getByRole('button', { name: 'تحديث البيانات' })).toBeEnabled();
});

test('imports employee roster from the attendance source on request', async ({ page }) => {
  const state = await openDashboard(page);
  await openAdminPanel(page);

  await page.getByRole('button', { name: 'جلب الموظفين من قاعدة البصمة' }).click();

  await expect.poll(() => state.employeeSyncRequests).toBe(1);
  await expect(page.getByText('تم جلب الموظفين من قاعدة البصمة: 1 جديد، 1 محدث.', { exact: true })).toBeVisible();
});

test('filters attendance and displays late-report analytics', async ({ page }) => {
  const state = await openDashboard(page);

  await page.getByLabel('التاريخ', { exact: true }).fill('2026-10-20');
  await page.getByLabel('رقم الموظف', { exact: true }).first().fill('16');
  await page.getByRole('button', { name: 'بحث' }).click();

  await expect.poll(() => state.attendanceSearch).toEqual({
    date: '2026-10-20',
    employee_id: '16',
  });
  await expect(page.getByText('2026-10-20').first()).toBeVisible();

  const reportSection = page.getByRole('heading', { name: 'تقرير التأخير' }).locator('..');
  await reportSection.getByLabel('من').fill('2026-10-01');
  await reportSection.getByLabel('إلى').fill('2026-10-24');
  await reportSection.getByRole('button', { name: 'عرض التقرير' }).click();

  await expect.poll(() => state.reportSearch).toEqual({
    from: '2026-10-01',
    to: '2026-10-24',
  });
  await expect(reportSection.getByText('إجمالي دقائق التأخير')).toBeVisible();
  await expect(reportSection.getByRole('row').filter({ hasText: 'سالم' })).toBeVisible();
});

test('edits a colored overnight shift using schema-shaped values', async ({ page }) => {
  const state = await openDashboard(page);
  await openAdminPanel(page);
  const nightShift = page.getByRole('article').filter({ hasText: 'مسائية' });

  await expect(nightShift).toContainText('22:00 – 06:00 (اليوم التالي)');
  await expect(nightShift.locator('.shift-color i')).toHaveCSS('background-color', 'rgb(124, 58, 237)');

  const shiftsSection = page.getByRole('heading', { name: 'إدارة الورديات' })
    .locator('..').locator('..').locator('..');
  await nightShift.getByRole('button', { name: 'تعديل' }).click();
  await expect(shiftsSection.getByLabel('من', { exact: true })).toHaveValue('22:00');
  await expect(shiftsSection.getByLabel('إلى', { exact: true })).toHaveValue('06:00');
  await expect(shiftsSection.getByLabel('لون الوردية')).toHaveValue('#7c3aed');
  await shiftsSection.getByLabel('اسم الوردية').fill('وردية ليلية');
  await shiftsSection.getByLabel('طريقة احتساب التأخير').selectOption('after_grace');
  await shiftsSection.getByLabel('لون الوردية').fill('#aabbcc');
  await shiftsSection.getByRole('button', { name: 'حفظ الوردية' }).click();

  await expect.poll(() => state.shiftUpdate).toMatchObject({
    id: 2,
    name: 'وردية ليلية',
    start_time: '22:00',
    end_time: '06:00',
    grace_period_minutes: 10,
    lateness_mode: 'after_grace',
    color: '#aabbcc',
    is_active: false,
  });
});

test('opens and saves a new shift from the add shift button', async ({ page }) => {
  const state = await openDashboard(page);
  await openAdminPanel(page);

  const shiftsSection = page.getByRole('heading', { name: 'إدارة الورديات' })
    .locator('..').locator('..').locator('..');
  await shiftsSection.getByRole('button', { name: 'إضافة وردية' }).click();

  await expect(shiftsSection.getByRole('heading', { name: 'إضافة وردية' })).toBeVisible();
  await shiftsSection.getByLabel('اسم الوردية').fill('وردية جديدة');
  await shiftsSection.getByRole('button', { name: 'حفظ الوردية' }).click();

  await expect.poll(() => state.shiftCreate).toMatchObject({
    name: 'وردية جديدة',
    start_time: '08:00',
    end_time: '17:00',
    grace_period_minutes: 15,
    lateness_mode: 'after_grace',
  });
});

test('assigns an employee to a shift with a future effective date', async ({ page }) => {
  const state = await openDashboard(page);
  await openAdminPanel(page);
  const assignmentForm = page.locator('form').filter({ hasText: 'تعيين أو تغيير وردية' });

  await assignmentForm.getByLabel('الموظف').selectOption('17');
  await assignmentForm.getByLabel('الوردية').selectOption('2');
  await assignmentForm.getByLabel('تاريخ النفاذ').fill('2099-11-01');
  await assignmentForm.getByRole('button', { name: 'حفظ التوزيع' }).click();

  await expect.poll(() => state.shiftAssignment).toEqual({
    employee_id: '17',
    shift_id: 2,
    start_date: '2099-11-01',
  });
  await expect(page.getByText('تم تحديث توزيع الوردية بتاريخ النفاذ المحدد', { exact: true })).toBeVisible();
});

test('shows loading then an API error without arbitrary sleeps', async ({ page }) => {
  const state = await mockApi(page, { holdInitialAttendance: true });
  await page.goto('/');

  await expect.poll(() => state.pendingAttendanceResolvers.length).toBeGreaterThan(0);
  await expect(page.getByText('جارٍ تحميل بيانات لوحة التحكم…', { exact: true })).toBeVisible();
  state.releaseAttendance();
  await expect(page.getByText('بوابة 1')).toBeVisible();

  state.holdAttendance = false;
  state.attendanceFailure = true;
  await page.getByRole('button', { name: 'تحديث البيانات' }).click();
  await expect(page.getByRole('alert')).toContainText('خدمة الحضور غير متاحة');
});

test('polls dashboard data and supports a manual refresh without waiting in real time', async ({ page }) => {
  const state = await mockApi(page);
  await page.clock.install();
  await page.goto('/');
  await expect(page.getByText('بوابة 1')).toBeVisible();
  const initialRequests = state.attendanceRequests;

  await page.clock.fastForward(30_000);
  await expect.poll(() => state.attendanceRequests).toBeGreaterThan(initialRequests);
  const afterPoll = state.attendanceRequests;

  await page.getByRole('button', { name: 'تحديث البيانات' }).click();
  await expect.poll(() => state.attendanceRequests).toBeGreaterThan(afterPoll);
});

test('submits a future branch transfer with its effective date', async ({ page }) => {
  const state = await openDashboard(page);
  await openAdminPanel(page);
  const branchSection = page.getByRole('heading', { name: 'نقل الموظفين وسجل الفروع' }).locator('..');
  const transferForm = branchSection.locator('form');

  await transferForm.getByLabel('الموظف').selectOption('16');
  await transferForm.getByLabel('الفرع الجديد').fill('فرع العليا');
  await transferForm.getByLabel('تاريخ النقل').fill('2099-12-01');
  await transferForm.getByLabel('ملاحظات').fill('نقل مستقبلي');
  await transferForm.getByRole('button', { name: 'حفظ النقل' }).click();

  await expect.poll(() => state.branchTransfer).toEqual({
    employee_id: '16',
    employee_name: 'سالم',
    branch_name: 'فرع العليا',
    start_date: '2099-12-01',
    notes: 'نقل مستقبلي',
  });
  await expect(page.getByText('تم نقل الموظف إلى الفرع بنجاح', { exact: true })).toBeVisible();
});

test('shows branch conflicts inline without relying on a browser dialog', async ({ page }) => {
  const state = await openDashboard(page, { branchConflict: true });
  await openAdminPanel(page);
  const branchSection = page.getByRole('heading', { name: 'نقل الموظفين وسجل الفروع' }).locator('..');
  const transferForm = branchSection.locator('form');

  await transferForm.getByLabel('الموظف').selectOption('16');
  await transferForm.getByLabel('الفرع الجديد').fill('فرع العليا');
  await transferForm.getByLabel('تاريخ النقل').fill('2026-11-01');
  await transferForm.getByRole('button', { name: 'حفظ النقل' }).click();

  await expect.poll(() => state.branchTransfer?.start_date).toBe('2026-11-01');
  await expect(page.getByRole('alert')).toContainText('تاريخ النقل يتداخل مع سجل فرع سابق');
});

test('confirms destructive shift deletion using Playwright dialog handling', async ({ page }) => {
  const state = await openDashboard(page);
  await openAdminPanel(page);
  const nightShift = page.getByRole('article').filter({ hasText: 'مسائية' });
  const dialogPromise = page.waitForEvent('dialog').then(async dialog => {
    expect(dialog.type()).toBe('confirm');
    await dialog.accept();
  });

  await nightShift.getByRole('button', { name: 'حذف' }).click();
  await dialogPromise;

  await expect.poll(() => state.shiftDelete).toBe(2);
  await expect(page.getByRole('article').filter({ hasText: 'مسائية' })).toHaveCount(0);
});
