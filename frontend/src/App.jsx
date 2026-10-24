import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import './App.css';

const dateKey = date => {
  const local = new Date(date.getTime() - date.getTimezoneOffset() * 60000);
  return local.toISOString().slice(0, 10);
};

const todayString = () => dateKey(new Date());

const daysAgoString = days => {
  const date = new Date();
  date.setDate(date.getDate() - days);
  return dateKey(date);
};

const asList = value => {
  if (Array.isArray(value)) return value;
  if (Array.isArray(value?.items)) return value.items;
  if (Array.isArray(value?.employees)) return value.employees;
  if (Array.isArray(value?.assignments)) return value.assignments;
  return [];
};

const getErrorMessage = (body, fallback) => {
  const detail = body?.detail;
  if (typeof detail === 'string') return detail;
  if (Array.isArray(detail)) return detail.map(item => item.msg || String(item)).join('، ');
  return fallback;
};

const employeeIdOf = employee => employee?.employee_id ?? employee?.id ?? employee?.person_id ?? '';
const employeeNameOf = employee => employee?.employee_name ?? employee?.name ?? employee?.person_name ?? '';
const shiftIdOf = assignment => assignment?.shift_id ?? assignment?.shift?.id ?? assignment?.shift?.shift_id;
const formatTime = value => (value ? String(value).slice(0, 5) : '—');

function timeDisplay(start, end) {
  const startTime = formatTime(start);
  const endTime = formatTime(end);
  if (!start || !end) return `${startTime} – ${endTime}`;
  return `${startTime} – ${endTime}${end <= start ? ' (اليوم التالي)' : ''}`;
}

function StatusMessage({ children, kind = 'info' }) {
  if (!children) return null;
  return <p className={`status-banner status-banner--${kind}`} role={kind === 'error' ? 'alert' : 'status'}>{children}</p>;
}

function DataTable({ children, className = '' }) {
  return <div className="table-wrap"><table className={`responsive-table ${className}`}>{children}</table></div>;
}

export default function App() {
  const [attendance, setAttendance] = useState(null);
  const [shifts, setShifts] = useState([]);
  const [employees, setEmployees] = useState([]);
  const [assignments, setAssignments] = useState([]);
  const [branches, setBranches] = useState({ items: [], total: 0 });
  const [lateReport, setLateReport] = useState(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [lastRefresh, setLastRefresh] = useState(null);
  const [loadError, setLoadError] = useState('');
  const [actionMessage, setActionMessage] = useState(null);
  const [accessToken, setAccessToken] = useState('');
  const [adminPanel, setAdminPanel] = useState(false);
  const [loginUsername, setLoginUsername] = useState('admin');
  const [loginPassword, setLoginPassword] = useState('');
  const [loginError, setLoginError] = useState('');
  const [loggingIn, setLoggingIn] = useState(false);

  // [البند 15] تتبع تاريخ الخادم المعتمد (بتوقيت الرياض)
  const [serverToday, setServerToday] = useState('');
  const userPickedDateRef = useRef(false);
  const [attendanceDate, setAttendanceDate] = useState(todayString());
  const [attendanceEmployeeId, setAttendanceEmployeeId] = useState('');
  const [reportFrom, setReportFrom] = useState(() => daysAgoString(6));
  const [reportTo, setReportTo] = useState(todayString());

  const [editingShiftId, setEditingShiftId] = useState(null);
  const [shiftFormOpen, setShiftFormOpen] = useState(false);
  const [shiftForm, setShiftForm] = useState({
    name: '',
    start_time: '08:00',
    end_time: '17:00',
    grace_period_minutes: 15,
    lateness_mode: 'after_grace',
    color: '#3b82f6',
    is_active: true,
  });
  const [employeeForm, setEmployeeForm] = useState({ employee_id: '', employee_name: '' });
  const [editingEmployeeId, setEditingEmployeeId] = useState(null);
  const [assignmentForm, setAssignmentForm] = useState({ employee_id: '', shift_id: '', start_date: todayString() });
  const [branchForm, setBranchForm] = useState({ employee_id: '', employee_name: '', branch_name: '', start_date: todayString(), notes: '' });
  const [attendanceSearchBusy, setAttendanceSearchBusy] = useState(false);
  const [reportBusy, setReportBusy] = useState(false);
  const [databaseSettings, setDatabaseSettings] = useState(null);
  const [databaseForm, setDatabaseForm] = useState({
    host: '',
    port: '3306',
    attendance_database: '',
    attendance_username: '',
    attendance_password: '',
  });
  const [databaseSettingsBusy, setDatabaseSettingsBusy] = useState(false);
  const [databaseTestBusy, setDatabaseTestBusy] = useState(false);
  const [databaseTestResult, setDatabaseTestResult] = useState(null);
  const [employeeSyncBusy, setEmployeeSyncBusy] = useState(false);

  const requestController = useRef(null);
  const refreshingRef = useRef(false);
  const mountedRef = useRef(true);
  const lastRefreshRef = useRef(null);
  const attendanceDateRef = useRef(attendanceDate);
  const attendanceEmployeeIdRef = useRef(attendanceEmployeeId);
  attendanceDateRef.current = attendanceDate;
  attendanceEmployeeIdRef.current = attendanceEmployeeId;

  const apiFetch = useCallback(async (path, options = {}) => {
    const response = await fetch(path, {
      ...options,
      headers: {
        ...options.headers,
        ...(accessToken ? { Authorization: `Bearer ${accessToken}` } : {}),
      },
    });
    if (response.status === 401 && accessToken) {
      setAccessToken('');
      setLoginError('انتهت الجلسة؛ سجّل الدخول مرة أخرى.');
    }
    return response;
  }, [accessToken]);

  const handleLogin = async event => {
    event.preventDefault();
    setLoggingIn(true);
    setLoginError('');
    try {
      const response = await fetch('/api/auth/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username: loginUsername, password: loginPassword }),
      });
      const body = await response.json().catch(() => ({}));
      if (!response.ok) {
        const fallback = response.status >= 500
          ? `خدمة تسجيل الدخول غير متاحة الآن (رمز ${response.status}). تحقق من تشغيل backend وإعداد اتصال قواعد البيانات.`
          : 'تعذر تسجيل الدخول';
        throw new Error(getErrorMessage(body, fallback));
      }
      setAccessToken(body.access_token);
      setAdminPanel(true);
      setLoginPassword('');
    } catch (error) {
      setLoginError(error instanceof TypeError
        ? 'تعذر الاتصال بخدمة تسجيل الدخول. تأكد من تشغيل backend على المنفذ 8000.'
        : error.message || 'تعذر تسجيل الدخول');
    } finally {
      setLoggingIn(false);
    }
  };

  const handleLogout = () => {
    requestController.current?.abort();
    setAccessToken('');
    setAdminPanel(false);
    setLoginPassword('');
    setLoginError('');
  };

  const refreshData = useCallback(async () => {
    if (refreshingRef.current || document.visibilityState === 'hidden') return;
    refreshingRef.current = true;
    const controller = new AbortController();
    requestController.current = controller;
    setRefreshing(true);
    setLoading(previous => previous && !lastRefreshRef.current);

    const read = async (path, label) => {
      const response = await apiFetch(path, { signal: controller.signal });
      const body = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(getErrorMessage(body, `تعذر تحميل ${label}`));
      return body;
    };

    try {
      const attendanceParams = new URLSearchParams();
      if (userPickedDateRef.current && attendanceDateRef.current) {
        attendanceParams.set('date', attendanceDateRef.current);
      }
      if (attendanceEmployeeIdRef.current.trim()) {
        attendanceParams.set('employee_id', attendanceEmployeeIdRef.current.trim());
      }
      const attendanceQuery = attendanceParams.toString();
      const attendancePath = attendanceQuery
        ? `/api/attendance?${attendanceQuery}`
        : '/api/attendance/today';

      const results = await Promise.allSettled([
        read(attendancePath, 'الحضور'),
        read('/api/shifts', 'الورديات'),
        read('/api/employees', 'الموظفين'),
        read('/api/employee-shifts', 'توزيع الورديات'),
        read('/api/employee-branches?limit=200', 'سجل الفروع'),
      ]);
      if (controller.signal.aborted || !mountedRef.current) return;

      const errors = [];
      const setters = [
        [setAttendance, 'الحضور'],
        [value => setShifts(asList(value)), 'الورديات'],
        [value => setEmployees(asList(value)), 'الموظفين'],
        [value => setAssignments(asList(value)), 'توزيع الورديات'],
        [value => setBranches(value || { items: [], total: 0 }), 'سجل الفروع'],
      ];
      results.forEach((result, index) => {
        const [setter, label] = setters[index];
        if (result.status === 'fulfilled') {
          setter(result.value);
          // [البند 15] مزامنة التاريخ مع استجابة الخادم لليوم الحالي
          if (label === 'الحضور' && result.value?.date) {
            const serverDateVal = result.value.date;
            setServerToday(serverDateVal);
            if (!userPickedDateRef.current) {
              setAttendanceDate(serverDateVal);
              setReportTo(serverDateVal);
            }
          }
        } else if (result.reason?.name !== 'AbortError') {
          errors.push(`${label}: ${result.reason?.message || 'حدث خطأ غير متوقع'}`);
        }
      });
      setLoadError(errors.join(' | '));
      if (errors.length === 0) {
        const refreshedAt = new Date();
        lastRefreshRef.current = refreshedAt;
        setLastRefresh(refreshedAt);
      }
      setLoading(false);
    } catch (error) {
      if (!controller.signal.aborted && mountedRef.current) {
        setLoadError(error.message || 'تعذر تحديث البيانات');
        setLoading(false);
      }
    } finally {
      if (requestController.current === controller) {
        refreshingRef.current = false;
        requestController.current = null;
        if (mountedRef.current) setRefreshing(false);
      }
    }
  }, [apiFetch]);

  useEffect(() => {
    mountedRef.current = true;
    refreshData();
    const interval = window.setInterval(() => {
      if (document.visibilityState === 'visible') refreshData();
    }, 30000);
    const onVisibilityChange = () => {
      if (document.visibilityState === 'visible') refreshData();
    };
    document.addEventListener('visibilitychange', onVisibilityChange);
    return () => {
      mountedRef.current = false;
      window.clearInterval(interval);
      document.removeEventListener('visibilitychange', onVisibilityChange);
      requestController.current?.abort();
      refreshingRef.current = false;
    };
  }, [refreshData]);

  useEffect(() => {
    if (!accessToken || !adminPanel) return undefined;
    const controller = new AbortController();
    const loadDatabaseSettings = async () => {
      try {
        const response = await apiFetch('/api/admin/database', { signal: controller.signal });
        const body = await response.json().catch(() => ({}));
        if (!response.ok) throw new Error(getErrorMessage(body, 'تعذر تحميل إعدادات قاعدة البيانات'));
        if (controller.signal.aborted) return;
        setDatabaseSettings(body);
        setDatabaseForm({
          host: body.host,
          port: String(body.port),
          attendance_database: body.attendance_database,
          attendance_username: body.attendance_username,
          attendance_password: '',
        });
      } catch (error) {
        if (!controller.signal.aborted) showDatabaseMessage(error.message || 'تعذر تحميل إعدادات قاعدة البيانات', 'error');
      }
    };
    loadDatabaseSettings();
    return () => controller.abort();
  }, [accessToken, adminPanel, apiFetch]);

  const showAction = (message, kind = 'info') => setActionMessage({ message, kind });
  const showDatabaseMessage = (message, kind = 'info') => setActionMessage({ message, kind });
  const requestJson = async (path, options = {}) => {
    const response = await apiFetch(path, options);
    const body = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(getErrorMessage(body, 'تعذر إتمام العملية'));
    return body;
  };
  const databasePayload = () => ({
    ...databaseForm,
    port: Number(databaseForm.port),
    attendance_password: databaseForm.attendance_password || null,
  });

  const testDatabaseConnection = async () => {
    setDatabaseTestBusy(true);
    setDatabaseTestResult(null);
    try {
      const result = await requestJson('/api/admin/database/test', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(databasePayload()),
      });
      setDatabaseTestResult(result);
      showDatabaseMessage(
        result.attendance_connected
          ? 'اتصال قاعدة البصمة ناجح.'
          : 'تعذر الاتصال بقاعدة البصمة؛ راجع البيانات قبل الحفظ.',
        result.attendance_connected ? 'success' : 'error',
      );
    } catch (error) {
      showDatabaseMessage(error.message, 'error');
    } finally {
      setDatabaseTestBusy(false);
    }
  };

  const saveDatabaseSettings = async event => {
    event.preventDefault();
    setDatabaseSettingsBusy(true);
    setDatabaseTestResult(null);
    try {
      const result = await requestJson('/api/admin/database', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(databasePayload()),
      });
      setDatabaseSettings(result.settings);
      setDatabaseForm(previous => ({ ...previous, attendance_password: '' }));
      showDatabaseMessage(result.message, 'success');
      await refreshData();
    } catch (error) {
      showDatabaseMessage(error.message, 'error');
    } finally {
      setDatabaseSettingsBusy(false);
    }
  };

  const syncEmployees = async () => {
    setEmployeeSyncBusy(true);
    try {
      const result = await requestJson('/api/employees/sync', { method: 'POST' });
      showAction(`تم جلب الموظفين من قاعدة البصمة: ${result.created} جديد، ${result.updated} محدث.`, 'success');
      await refreshData();
    } catch (error) {
      showAction(error.message || 'تعذر جلب الموظفين من قاعدة البصمة.', 'error');
    } finally {
      setEmployeeSyncBusy(false);
    }
  };

  const handleAttendanceSearch = async event => {
    event.preventDefault();
    userPickedDateRef.current = true;
    setAttendanceSearchBusy(true);
    setLoadError('');
    const params = new URLSearchParams();
    if (attendanceDate) params.set('date', attendanceDate);
    const search = attendanceEmployeeId.trim();
    if (search) {
      const normalized = search.toLocaleLowerCase('ar');
      const exactId = employees.find(employee => String(employeeIdOf(employee)) === search);
      const nameMatches = employees.filter(employee =>
        String(employeeNameOf(employee)).trim().toLocaleLowerCase('ar').includes(normalized)
      );
      const exactName = nameMatches.filter(employee =>
        String(employeeNameOf(employee)).trim().toLocaleLowerCase('ar') === normalized
      );
      const match = exactId || (exactName.length === 1 ? exactName[0] : nameMatches.length === 1 ? nameMatches[0] : null);
      if (match) {
        params.set('employee_id', String(employeeIdOf(match)));
      } else if (/^\d+$/.test(search)) {
        params.set('employee_id', search);
      } else {
        setLoadError(nameMatches.length > 1
          ? 'الاسم يطابق أكثر من موظف؛ اكتب الاسم كاملاً أو رقم الموظف.'
          : 'لم أجد موظفاً بهذا الاسم. جرّب رقم الموظف أو زامن قائمة الموظفين.');
        setAttendanceSearchBusy(false);
        return;
      }
    }
    try {
      const body = await requestJson(`/api/attendance?${params.toString()}`);
      setAttendance(body);
      setActionMessage(null);
    } catch (error) {
      setLoadError(error.message);
    } finally {
      setAttendanceSearchBusy(false);
    }
  };

  const loadLateReport = useCallback(async (from, to) => {
    setReportBusy(true);
    const params = new URLSearchParams();
    if (from) params.set('from', from);
    if (to) params.set('to', to);
    try {
      const response = await apiFetch(`/api/reports/late?${params.toString()}`);
      const body = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(getErrorMessage(body, 'تعذر تحميل تقرير التأخير'));
      setLateReport(body);
      setActionMessage(null);
    } catch (error) {
      setLateReport(null);
      showAction(error.message || 'تعذر تحميل تقرير التأخير', 'error');
    } finally {
      setReportBusy(false);
    }
  }, [apiFetch]);

  useEffect(() => {
    loadLateReport(reportFrom, reportTo);
  }, [loadLateReport]);

  const handleLateReport = event => {
    event.preventDefault();
    loadLateReport(reportFrom, reportTo);
  };

  // [البند 15] حساب الفترات اعتماداً على تاريخ الخادم الفعلي
  const chooseReportPeriod = period => {
    const today = serverToday ? new Date(serverToday + 'T00:00:00') : new Date();
    let from = serverToday || todayString();
    let to = serverToday || todayString();
    if (period === 'week') {
      const d = new Date(today);
      d.setDate(d.getDate() - 6);
      from = dateKey(d);
    }
    if (period === 'month') {
      const d = new Date(today);
      d.setDate(d.getDate() - 29);
      from = dateKey(d);
    }
    if (period === 'this-month') from = dateKey(new Date(today.getFullYear(), today.getMonth(), 1));
    if (period === 'last-month') {
      from = dateKey(new Date(today.getFullYear(), today.getMonth() - 1, 1));
      to = dateKey(new Date(today.getFullYear(), today.getMonth(), 0));
    }
    setReportFrom(from);
    setReportTo(to);
    loadLateReport(from, to);
  };

  const beginShiftForm = shift => {
    setEditingShiftId(shift?.id ?? null);
    setShiftFormOpen(true);
    setShiftForm(shift ? {
      name: shift.name || '',
      start_time: formatTime(shift.start_time),
      end_time: formatTime(shift.end_time),
      grace_period_minutes: shift.grace_period_minutes ?? 15,
      lateness_mode: shift.lateness_mode || 'after_grace',
      color: shift.color || '#3b82f6',
      is_active: Boolean(shift.is_active),
    } : {
      name: '',
      start_time: '08:00',
      end_time: '17:00',
      grace_period_minutes: 15,
      lateness_mode: 'after_grace',
      color: '#3b82f6',
      is_active: true,
    });
  };

  const saveShift = async event => {
    event.preventDefault();
    try {
      const path = editingShiftId ? `/api/shifts/${editingShiftId}` : '/api/shifts';
      await requestJson(path, {
        method: editingShiftId ? 'PUT' : 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          ...shiftForm,
          grace_period_minutes: Number(shiftForm.grace_period_minutes),
        }),
      });
      setEditingShiftId(null);
      setShiftFormOpen(false);
      showAction('تم حفظ الوردية بنجاح', 'success');
      await refreshData();
    } catch (error) {
      showAction(error.message, 'error');
    }
  };

  const deleteShift = async shift => {
    if (!window.confirm(`حذف الوردية «${shift.name}»؟`)) return;
    try {
      await requestJson(`/api/shifts/${shift.id}`, { method: 'DELETE' });
      showAction('تم حذف الوردية', 'success');
      await refreshData();
    } catch (error) {
      showAction(error.message, 'error');
    }
  };

  const saveEmployee = async event => {
    event.preventDefault();
    const id = editingEmployeeId || employeeForm.employee_id.trim();
    const payload = {
      employee_id: employeeForm.employee_id.trim(),
      employee_name: employeeForm.employee_name.trim(),
    };
    try {
      await requestJson(editingEmployeeId ? `/api/employees/${encodeURIComponent(id)}` : '/api/employees', {
        method: editingEmployeeId ? 'PUT' : 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      setEmployeeForm({ employee_id: '', employee_name: '' });
      setEditingEmployeeId(null);
      showAction('تم حفظ بيانات الموظف', 'success');
      await refreshData();
    } catch (error) {
      showAction(error.message, 'error');
    }
  };

  const beginEmployeeEdit = employee => {
    const id = employeeIdOf(employee);
    setEditingEmployeeId(String(id));
    setEmployeeForm({
      employee_id: String(id),
      employee_name: String(employeeNameOf(employee)),
    });
  };

  const deactivateEmployee = async employee => {
    const id = employeeIdOf(employee);
    if (!window.confirm(`إيقاف الموظف ${employeeNameOf(employee) || id}؟`)) return;
    try {
      await requestJson(`/api/employees/${encodeURIComponent(id)}/deactivate`, { method: 'POST' });
      showAction('تم إيقاف الموظف', 'success');
      await refreshData();
    } catch (error) {
      showAction(error.message, 'error');
    }
  };

  // [البند 5] زر تفعيل الموظف الموقوف
  const activateEmployee = async employee => {
    const id = employeeIdOf(employee);
    if (!window.confirm(`إعادة تفعيل الموظف «${employeeNameOf(employee) || id}»؟`)) return;
    try {
      try {
        await requestJson(`/api/employees/${encodeURIComponent(id)}/activate`, { method: 'POST' });
      } catch {
        await requestJson(`/api/employees/${encodeURIComponent(id)}`, {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ active: true }),
        });
      }
      showAction('تمت إعادة تفعيل الموظف بنجاح', 'success');
      await refreshData();
    } catch (error) {
      showAction(error.message, 'error');
    }
  };

  const assignShift = async event => {
    event.preventDefault();
    try {
      await requestJson('/api/employee-shifts', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          employee_id: assignmentForm.employee_id,
          shift_id: Number(assignmentForm.shift_id),
          start_date: assignmentForm.start_date,
        }),
      });
      showAction('تم تحديث توزيع الوردية بتاريخ النفاذ المحدد', 'success');
      await refreshData();
    } catch (error) {
      showAction(error.message, 'error');
    }
  };

  // [البند 4] حذف آخر تكليف وردية للموظف مع رسالة تأكيد تحذيرية
  const deleteLastShiftAssignment = async assignment => {
    const emp = employees.find(e => String(employeeIdOf(e)) === String(assignment.employee_id));
    const empName = emp ? employeeNameOf(emp) : assignment.employee_id;
    const message = `⚠️ تحذير: هل أنت متأكد من حذف آخر تكليف وردية للموظف «${empName}»؟\n\nسيتم التراجع عن هذا التكليف واستعادة التكليف السابق المفتوح إن وجد.`;
    if (!window.confirm(message)) return;
    try {
      await requestJson(`/api/employee-shifts/${assignment.id}`, { method: 'DELETE' });
      showAction('تم حذف آخر تكليف وردية واستعادة التكليف السابق بنجاح', 'success');
      await refreshData();
    } catch (error) {
      showAction(error.message, 'error');
    }
  };

  // [البند 4] حذف آخر نقل فرع للموظف مع رسالة تأكيد تحذيرية
  const deleteLastBranchRecord = async record => {
    const empName = record.employee_name || record.employee_id;
    const message = `⚠️ تحذير: هل أنت متأكد من حذف آخر سجل نقل للموظف «${empName}» إلى فرع «${record.branch_name}»؟\n\nسيتم التراجع عن هذا النقل واستعادة السجل السابق إن وجد.`;
    if (!window.confirm(message)) return;
    try {
      await requestJson(`/api/employee-branches/${record.id}`, { method: 'DELETE' });
      showAction('تم حذف آخر سجل نقل واستعادة السجل السابق بنجاح', 'success');
      await refreshData();
    } catch (error) {
      showAction(error.message, 'error');
    }
  };

  const transferBranch = async event => {
    event.preventDefault();
    try {
      await requestJson('/api/employee-branches', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          employee_id: branchForm.employee_id.trim(),
          employee_name: branchForm.employee_name.trim() || null,
          branch_name: branchForm.branch_name.trim(),
          start_date: branchForm.start_date,
          notes: branchForm.notes.trim() || null,
        }),
      });
      setBranchForm({ employee_id: '', employee_name: '', branch_name: '', start_date: serverToday || todayString(), notes: '' });
      showAction('تم نقل الموظف إلى الفرع بنجاح', 'success');
      await refreshData();
    } catch (error) {
      showAction(error.message, 'error');
    }
  };

  const currentAssignments = useMemo(() => {
    const today = attendance?.date || serverToday || todayString();
    const byEmployee = new Map();
    assignments.forEach(assignment => {
      const employeeId = String(assignment.employee_id ?? '');
      const start = assignment.start_date ?? assignment.effective_from ?? '';
      const end = assignment.end_date ?? assignment.effective_to ?? '';
      if (!employeeId || start > today || (end && end < today)) return;
      const previous = byEmployee.get(employeeId);
      if (!previous || String(previous.start_date || previous.effective_from || '') < String(start)) {
        byEmployee.set(employeeId, assignment);
      }
    });
    return byEmployee;
  }, [assignments, attendance?.date, serverToday]);

  const upcomingAssignments = useMemo(() => {
    const today = attendance?.date || serverToday || todayString();
    const byEmployee = new Map();
    assignments.forEach(assignment => {
      const employeeId = String(assignment.employee_id ?? '');
      const start = assignment.start_date ?? assignment.effective_from ?? '';
      const end = assignment.end_date ?? assignment.effective_to ?? '';
      if (!employeeId || !start || start <= today || (end && end < start)) return;
      const previous = byEmployee.get(employeeId);
      if (!previous || String(previous.start_date || previous.effective_from || '') > String(start)) {
        byEmployee.set(employeeId, assignment);
      }
    });
    return byEmployee;
  }, [assignments, attendance?.date, serverToday]);

  // استخراج أحدث معرف تكليف لكل موظف للسماح بحذف آخر سجل فقط
  const latestAssignmentIds = useMemo(() => {
    const seen = new Set();
    const latestIds = new Set();
    assignments.forEach(assign => {
      const empId = String(assign.employee_id || '');
      if (empId && !seen.has(empId)) {
        seen.add(empId);
        latestIds.add(assign.id);
      }
    });
    return latestIds;
  }, [assignments]);

  const branchesList = asList(branches);

  // استخراج أحدث معرف نقل لكل موظف للسماح بحذف آخر سجل فقط
  const latestBranchRecordIds = useMemo(() => {
    const seen = new Set();
    const latestIds = new Set();
    branchesList.forEach(rec => {
      const empId = String(rec.employee_id || '');
      if (empId && !seen.has(empId)) {
        seen.add(empId);
        latestIds.add(rec.id);
      }
    });
    return latestIds;
  }, [branchesList]);

  const activeEmployees = employees.filter(employee => employee.is_active !== false && employee.active !== false);
  const unassignedEmployees = activeEmployees.filter(employee => {
    const id = String(employeeIdOf(employee));
    return !currentAssignments.has(id) && !upcomingAssignments.has(id);
  });
  const logs = asList(attendance?.logs);
  const uniquePunchEmployees = new Set(
    logs
      .map(log => String(log.employee_id ?? '').trim())
      .filter(employeeId => employeeId && employeeId !== 'Unknown')
  ).size;
  const lateEmployees = asList(attendance?.late_employees);
  const activeShifts = shifts.filter(shift => shift.is_active);

  const shiftNameForAssignment = assignment => {
    const shiftId = shiftIdOf(assignment);
    const shift = shifts.find(item => String(item.id) === String(shiftId));
    return assignment?.shift_name || assignment?.shift?.name || shift?.name || `وردية ${shiftId ?? 'غير معروفة'}`;
  };

  // [البند 9] ملخص الحضور اليومي للموظفين الذين سجلوا بصمة
  const dailyEmployeeSummaries = useMemo(() => {
    const map = new Map();
    const sortedLogs = [...logs].sort((a, b) =>
      String(a.check_time || a.time || '').localeCompare(String(b.check_time || b.time || ''))
    );

    sortedLogs.forEach(log => {
      const id = String(log.employee_id || '').trim();
      if (!id || id === 'Unknown') return;
      if (!map.has(id)) {
        const emp = employees.find(e => String(employeeIdOf(e)) === id);
        const assignment = currentAssignments.get(id);
        const late = lateEmployees.find(l => String(l.employee_id) === id);
        map.set(id, {
          employee_id: id,
          employee_name: emp ? employeeNameOf(emp) : (log.employee_name || id),
          shift_name: assignment ? shiftNameForAssignment(assignment) : (log.shift_name || 'غير محددة'),
          punches: [],
          late: late || null,
        });
      }
      map.get(id).punches.push(log);
    });

    return Array.from(map.values()).map(item => {
      const times = item.punches.map(p => formatTime(p.check_time || p.time));
      return {
        ...item,
        first_punch: times[0] || '—',
        last_punch: times.length > 1 ? times[times.length - 1] : times[0] || '—',
        punch_count: item.punches.length,
      };
    });
  }, [logs, employees, currentAssignments, lateEmployees, shifts]);

  // [البند 9] الموظفون النشطون المجدولون الذين لم يسجلوا بصمة بعد اليوم
  const scheduledEmployeesWithoutPunches = useMemo(() => {
    const punchedIds = new Set(logs.map(log => String(log.employee_id || '').trim()));
    return activeEmployees.filter(emp => {
      const id = String(employeeIdOf(emp));
      const hasAssignment = currentAssignments.has(id);
      const hasPunched = punchedIds.has(id);
      return hasAssignment && !hasPunched;
    });
  }, [activeEmployees, currentAssignments, logs]);

  return (
    <main className="app-shell" dir="rtl">
      <header className="app-header">
        <div>
          <p className="app-kicker">راصد · متابعة الحضور والانصراف</p>
          <h1>{adminPanel ? 'راصد | لوحة المشرف' : 'راصد | لوحة متابعة الحضور'}</h1>
          <p>{adminPanel ? 'إدارة الورديات وتوزيع الموظفين وسجلات الفروع.' : 'نظرة شاملة ولحظية لحركات الحضور والورديات وسجلات الفروع والتقارير.'}</p>
        </div>
        <div className="header-controls">
          <button type="button" onClick={refreshData} disabled={refreshing}>{refreshing ? 'جارٍ التحديث…' : 'تحديث البيانات'}</button>
          {accessToken ? <>
            <button type="button" className="button-secondary" onClick={() => setAdminPanel(true)}>إدارة البيانات</button>
            <button type="button" className="button-secondary" onClick={handleLogout}>تسجيل الخروج</button>
          </> : <button type="button" className="button-secondary" onClick={() => { setLoginError(''); setAdminPanel(true); }}>دخول المشرف</button>}
        </div>
      </header>

      {adminPanel && (
        <nav className="page-nav" aria-label="تنقل المشرف">
          <button type="button" onClick={() => setAdminPanel(false)}>العودة للوحة الرئيسية</button>
        </nav>
      )}

      <StatusMessage kind={loadError ? 'error' : 'info'}>
        {loading
          ? 'جارٍ تحميل بيانات لوحة التحكم…'
          : `${loadError ? `${loadError} · ` : ''}آخر تحديث ناجح: ${lastRefresh ? lastRefresh.toLocaleTimeString('ar') : 'لا يوجد بعد'}${refreshing ? ' · جارٍ التحديث' : ''}`}
      </StatusMessage>
      <StatusMessage kind={actionMessage?.kind}>{actionMessage?.message}</StatusMessage>

      {adminPanel && !accessToken && (
        <section className="card login-card">
          <h2>دخول المشرف</h2>
          <p>تسجيل الدخول مطلوب لإدارة بيانات النظام. اسم المستخدم الرسمي: admin.</p>
          <form className="login-form" onSubmit={handleLogin}>
            <label htmlFor="login-username">اسم المستخدم</label>
            <input
              id="login-username"
              autoComplete="username"
              value={loginUsername}
              onChange={event => setLoginUsername(event.target.value)}
              required
            />
            <label htmlFor="login-password">كلمة المرور</label>
            <input
              id="login-password"
              type="password"
              autoComplete="current-password"
              value={loginPassword}
              onChange={event => setLoginPassword(event.target.value)}
              required
            />
            {loginError && <StatusMessage kind="error">{loginError}</StatusMessage>}
            <button type="submit" disabled={loggingIn}>
              {loggingIn ? 'جارٍ التحقق…' : 'تسجيل الدخول'}
            </button>
          </form>
        </section>
      )}

      {!adminPanel && <>
      <section className="summary-grid" aria-label="ملخص الحضور">
        <article className="card summary-card"><span>موظفون لديهم بصمات</span><strong>{attendance ? uniquePunchEmployees : '—'}</strong><small>موظفون مميزون في السجلات المعروضة</small></article>
        <article className="card summary-card"><span>إجمالي حركات البصمة</span><strong>{attendance ? attendance.total_records_processed ?? logs.length : '—'}</strong><small>{attendance?.date || serverToday || 'بانتظار البيانات'}</small></article>
        <article className="card summary-card"><span>موظفون متأخرون</span><strong>{attendance ? lateEmployees.length : '—'}</strong><small>حالات تأخير مسجلة فقط</small></article>
        <article className="card summary-card"><span>لم يسجل بصمة بعد</span><strong>{scheduledEmployeesWithoutPunches.length}</strong><small>موظفون مجدولون نشطون</small></article>
        <article className="card summary-card"><span>موظفون نشطون</span><strong>{employees.length ? activeEmployees.length : '—'}</strong><small>بحسب سجل الموظفين</small></article>
        <article className="card summary-card"><span>ورديات نشطة</span><strong>{shifts.length ? activeShifts.length : '—'}</strong><small>{shifts.length} إجمالي الورديات</small></article>
      </section>

      <section className="dashboard-analysis">
        <article className="card chart-card">
          <div className="section-heading">
            <div><p className="eyebrow">تحليل الموظفين</p><h2>الأكثر تأخراً في الفترة</h2></div>
            <span className="period-caption">{lateReport ? `${lateReport.from_date} إلى ${lateReport.to_date}` : 'جارٍ تحميل آخر 7 أيام…'}</span>
          </div>
          <EmployeeLateChart employees={asList(lateReport?.employees)} />
        </article>
        <article className="card analysis-card">
          <p className="eyebrow">ملخص الفترة</p>
          <h2>مؤشرات التأخير</h2>
          <div className="analysis-stat"><span>حالات تأخير (موظف/يوم)</span><strong>{lateReport?.total_late_days ?? '—'}</strong></div>
          <div className="analysis-stat"><span>إجمالي دقائق التأخير</span><strong>{lateReport?.total_late_minutes ?? '—'}</strong></div>
          <div className="analysis-stat"><span>موظفون تأخروا</span><strong>{asList(lateReport?.employees).length || (lateReport ? 0 : '—')}</strong></div>
          <p className="data-note">يُحسب هذا الملخص من سجلات التأخير المسجلة فقط.</p>
        </article>
      </section>

      {/* [البند 9] الملخص اليومي لحضور الموظفين */}
      <section className="card attendance-section">
        <div className="section-heading">
          <div>
            <h2>الملخص اليومي لحضور الموظفين</h2>
            <p>متابعة فورية ومباشرة لحضور وانصراف الموظفين لليوم ({attendance?.date || serverToday || todayString()}).</p>
          </div>
        </div>

        <h3>الموظفون الحاضرون اليوم ({dailyEmployeeSummaries.length})</h3>
        {dailyEmployeeSummaries.length === 0 ? (
          <p className="empty-state">لم يتم تسجيل أي حركة بصمة في هذا اليوم حتى الآن.</p>
        ) : (
          <DataTable>
            <thead>
              <tr>
                <th>رقم الموظف</th>
                <th>اسم الموظف</th>
                <th>الوردية</th>
                <th>أول بصمة (حضور)</th>
                <th>آخر بصمة</th>
                <th>عدد البصمات</th>
                <th>الحالة / التأخير</th>
              </tr>
            </thead>
            <tbody>
              {dailyEmployeeSummaries.map(item => (
                <tr key={item.employee_id}>
                  <td data-label="رقم الموظف">{item.employee_id}</td>
                  <td data-label="اسم الموظف"><strong>{item.employee_name}</strong></td>
                  <td data-label="الوردية">وردية: {item.shift_name}</td>
                  <td data-label="أول بصمة (حضور)">{item.first_punch}</td>
                  <td data-label="آخر بصمة">{item.last_punch}</td>
                  <td data-label="عدد البصمات"><span className="badge badge--neutral">{item.punch_count}</span></td>
                  <td data-label="الحالة / التأخير">
                    {item.late ? (
                      <span className="badge badge--warning">متأخر {item.late.late_minutes} دقيقة</span>
                    ) : (
                      <span className="badge badge--success">في الموعد</span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </DataTable>
        )}

        {/* [البند 9] قسم لم يسجل بصمة بعد */}
        <div style={{ marginBlockStart: '2rem' }}>
          <div className="section-heading">
            <div>
              <h3>لم يسجل بصمة بعد ({scheduledEmployeesWithoutPunches.length})</h3>
              <p>موظفون نشطون لديهم وردية مجدولة اليوم ولم تُسجّل لهم بصمة بعد (ملاحظة: هذا لا يعني الغياب الرسمي).</p>
            </div>
          </div>
          {scheduledEmployeesWithoutPunches.length === 0 ? (
            <p className="empty-state">جميع الموظفين المجدولين اليوم سجلوا بصماتهم.</p>
          ) : (
            <DataTable>
              <thead>
                <tr>
                  <th>رقم الموظف</th>
                  <th>اسم الموظف</th>
                  <th>الوردية المجدولة</th>
                  <th>فترة الوردية</th>
                  <th>الحالة</th>
                </tr>
              </thead>
              <tbody>
                {scheduledEmployeesWithoutPunches.map(emp => {
                  const id = String(employeeIdOf(emp));
                  const name = employeeNameOf(emp);
                  const assignment = currentAssignments.get(id);
                  const shift = shifts.find(s => String(s.id) === String(shiftIdOf(assignment)));
                  return (
                    <tr key={id}>
                      <td data-label="رقم الموظف">{id}</td>
                      <td data-label="اسم الموظف"><strong>{name || id}</strong></td>
                      <td data-label="الوردية المجدولة">{shift?.name || shiftNameForAssignment(assignment)}</td>
                      <td data-label="فترة الوردية">{shift ? timeDisplay(shift.start_time, shift.end_time) : '—'}</td>
                      <td data-label="الحالة"><span className="badge badge--warning">بانتظار تسجيل البصمة</span></td>
                    </tr>
                  );
                })}
              </tbody>
            </DataTable>
          )}
        </div>
      </section>

      <section className="card attendance-section">
        <div className="section-heading">
          <div><h2>سجل حركات البصمات والبحث</h2><p>ابحث بالتاريخ أو رقم الموظف، ولا تُفسّر الأيام بلا بصمة على أنها غياب.</p></div>
        </div>
        <form className="form-grid attendance-filters" onSubmit={handleAttendanceSearch}>
          <label>التاريخ<input type="date" value={attendanceDate} onChange={event => { userPickedDateRef.current = true; setAttendanceDate(event.target.value); }} /></label>
          <label>رقم الموظف<input type="search" value={attendanceEmployeeId} onChange={event => setAttendanceEmployeeId(event.target.value)} placeholder="جميع الموظفين أو رقم الموظف" /></label>
          <button type="submit" disabled={attendanceSearchBusy}>{attendanceSearchBusy ? 'جارٍ البحث…' : 'بحث'}</button>
        </form>
        {!attendance && !loading && <p className="empty-state">لا توجد بيانات حضور متاحة.</p>}
        {attendance && (
          <>
            <div className="analytics-strip">
              <p><strong>التاريخ:</strong> {attendance.date || '—'}</p>
              <p><strong>إجمالي الحركات:</strong> {attendance.total_records_processed ?? logs.length}</p>
              {attendance.daily_values && <MiniTrend values={attendance.daily_values} />}
            </div>
            <h3>التأخيرات المسجلة</h3>
            {lateEmployees.length === 0 ? <p className="empty-state">لا توجد حالات تأخير مسجلة لهذه النتائج.</p> : (
              <DataTable>
                <thead><tr><th>رقم الموظف</th><th>الاسم</th><th>وقت الحضور</th><th>التأخير</th></tr></thead>
                <tbody>{lateEmployees.map((employee, index) => (
                  <tr key={`${employee.employee_id}-${index}`}>
                    <td data-label="رقم الموظف">{employee.employee_id}</td>
                    <td data-label="الاسم">{employeeNameOf(employee) || '—'}</td>
                    <td data-label="وقت الحضور">{employee.arrival_time || '—'}</td>
                    <td data-label="التأخير">{employee.late_minutes ?? '—'} دقيقة</td>
                  </tr>
                ))}</tbody>
              </DataTable>
            )}
            <h3>سجل الحركات التفصيلي</h3>
            {logs.length === 0 ? <p className="empty-state">لا توجد بصمات مطابقة للفلاتر.</p> : (
              <DataTable>
                <thead><tr><th>رقم الموظف</th><th>الاسم</th><th>الوقت</th><th>الوردية المرتبطة</th><th>التفاصيل</th><th>الجهاز</th></tr></thead>
                <tbody>{logs.map((log, index) => {
                  const association = log.shift_association || log.employee_shift || log.shift || {};
                  return <tr key={`${log.employee_id}-${log.check_time}-${index}`}>
                    <td data-label="رقم الموظف">{log.employee_id}</td>
                    <td data-label="الاسم">{log.employee_name || '—'}</td>
                    <td data-label="الوقت">{log.check_time || log.time || '—'}</td>
                    <td data-label="الوردية المرتبطة">{association.name || log.shift_name || (log.shift_id ? `وردية ${log.shift_id}` : 'غير محددة')}</td>
                    <td data-label="التفاصيل">{log.lateness_mode || log.late_minutes != null ? `${log.lateness_mode || ''}${log.late_minutes != null ? ` · ${log.late_minutes} دقيقة تأخير` : ''}` : '—'}</td>
                    <td data-label="الجهاز">{log.device || '—'}</td>
                  </tr>;
                })}</tbody>
              </DataTable>
            )}
          </>
        )}
      </section>

      <section className="card">
        <div className="section-heading"><div><h2>الموظفون والورديات</h2><p>بيانات العرض للموظفين الداخليين؛ التعديل متاح للمشرف فقط.</p></div></div>
        {!employees.length && !loading && <p className="empty-state">لا توجد بيانات موظفين للعرض.</p>}
        {employees.length > 0 && (
          <DataTable>
            <thead><tr><th>رقم الموظف</th><th>الاسم</th><th>الحالة</th><th>الوردية</th><th>تاريخ النفاذ</th></tr></thead>
            <tbody>{employees.map(employee => {
              const id = String(employeeIdOf(employee));
              const assignment = currentAssignments.get(id);
              const upcomingAssignment = upcomingAssignments.get(id);
              return <tr key={id}>
                <td data-label="رقم الموظف">{id}</td>
                <td data-label="الاسم">{employeeNameOf(employee) || '—'}</td>
                <td data-label="الحالة"><span className={`badge ${employee.is_active === false || employee.active === false ? 'badge--muted' : 'badge--success'}`}>{employee.is_active === false || employee.active === false ? 'موقوف' : 'نشط'}</span></td>
                <td data-label="الوردية">{assignment ? shiftNameForAssignment(assignment) : upcomingAssignment ? `مجدول: ${shiftNameForAssignment(upcomingAssignment)}` : 'غير معيّن'}</td>
                <td data-label="تاريخ النفاذ">{assignment?.start_date || assignment?.effective_from || upcomingAssignment?.start_date || upcomingAssignment?.effective_from || '—'}</td>
              </tr>;
            })}</tbody>
          </DataTable>
        )}
        <h3>الورديات</h3>
        <div className="shift-list">
          {shifts.map(shift => <article className="shift-item" key={shift.id}>
            <span className="shift-color"><i style={{ backgroundColor: shift.color || '#94a3b8' }} />{shift.name}</span>
            <span>{timeDisplay(shift.start_time, shift.end_time)}</span>
            <span>سماح {shift.grace_period_minutes ?? 0} دقيقة</span>
            <span className={`badge ${shift.is_active ? 'badge--success' : 'badge--muted'}`}>{shift.is_active ? 'نشطة' : 'غير نشطة'}</span>
          </article>)}
        </div>
      </section>

      <section className="card">
        <h2>سجل الفروع</h2>
        {branchesList.length === 0 ? <p className="empty-state">لا توجد سجلات فروع للعرض.</p> : (
          <DataTable>
            <thead><tr><th>الموظف</th><th>الفرع</th><th>من</th><th>إلى</th><th>ملاحظات</th></tr></thead>
            <tbody>{branchesList.map(record => <tr key={record.id}>
              <td data-label="الموظف">{record.employee_name || record.employee_id} ({record.employee_id})</td>
              <td data-label="الفرع">{record.branch_name}</td><td data-label="من">{record.start_date}</td>
              <td data-label="إلى">{record.is_future ? `مجدول من ${record.start_date}` : record.is_current ? 'حالي' : record.end_date || 'سجل تاريخي'}</td>
              <td data-label="ملاحظات">{record.notes || '—'}</td>
            </tr>)}</tbody>
          </DataTable>
        )}
      </section>

      <section className="card report-page">
        <h2>تقرير التأخير</h2>
        <p>يعرض التأخيرات المسجلة فقط؛ عدم وجود بصمة لا يعني الغياب.</p>
        <div className="report-presets" aria-label="فترات جاهزة">
          <button type="button" className="button-secondary" onClick={() => chooseReportPeriod('week')}>آخر 7 أيام</button>
          <button type="button" className="button-secondary" onClick={() => chooseReportPeriod('month')}>آخر 30 يوماً</button>
          <button type="button" className="button-secondary" onClick={() => chooseReportPeriod('this-month')}>هذا الشهر</button>
          <button type="button" className="button-secondary" onClick={() => chooseReportPeriod('last-month')}>الشهر الماضي</button>
        </div>
        <form className="form-grid report-filters" onSubmit={handleLateReport}>
          <label>من<input type="date" value={reportFrom} onChange={event => setReportFrom(event.target.value)} /></label>
          <label>إلى<input type="date" value={reportTo} onChange={event => setReportTo(event.target.value)} /></label>
          <button type="submit" disabled={reportBusy}>{reportBusy ? 'جارٍ التحميل…' : 'عرض التقرير'}</button>
        </form>
        {!lateReport && <p className="empty-state">اختر الفترة لعرض التقرير.</p>}
        {lateReport && <>
          <p>الفترة: {lateReport.from_date} إلى {lateReport.to_date} · الوردية: {lateReport.shift_name || '—'}</p>
          <div className="summary-grid report-summary">
            <article className="card"><span>أيام التأخير المسجلة</span><strong>{lateReport.total_late_days ?? 0}</strong></article>
            <article className="card"><span>إجمالي دقائق التأخير</span><strong>{lateReport.total_late_minutes ?? 0}</strong></article>
          </div>
          {lateReport.daily_values && <MiniTrend values={lateReport.daily_values} />}
          {!asList(lateReport.employees).length ? <p className="empty-state">لا توجد تأخيرات في هذه الفترة.</p> : (
            <DataTable>
              <thead><tr><th>رقم الموظف</th><th>الاسم</th><th>أيام التأخير</th><th>الدقائق</th><th>متوسط الدقائق في يوم التأخير</th></tr></thead>
              <tbody>{asList(lateReport.employees).map(employee => <tr key={employee.employee_id}>
                <td data-label="رقم الموظف">{employee.employee_id}</td><td data-label="الاسم">{employeeNameOf(employee) || '—'}</td>
                <td data-label="أيام التأخير">{employee.late_days}</td><td data-label="الدقائق">{employee.total_late_minutes}</td>
                <td data-label="متوسط الدقائق">{employee.average_late_minutes}</td>
              </tr>)}</tbody>
            </DataTable>
          )}
        </>}
      </section>
      </>}

      {adminPanel && accessToken && <>
      <section className="card">
        <div className="section-heading">
          <div>
            <h2>اتصال قاعدة البصمة</h2>
            <p>قاعدة راصد الأساسية ثابتة ضمن إعداد المشروع. هذه الصفحة مخصصة لاتصال قاعدة البصمة فقط.</p>
          </div>
        </div>
        {databaseSettings && (
          <StatusMessage kind={databaseSettings.attendance_password_set ? 'success' : 'warning'}>
            {databaseSettings.attendance_password_set
              ? 'كلمة مرور قاعدة البصمة محفوظة. اترك الحقل فارغاً للاحتفاظ بها.'
              : 'أدخل كلمة مرور قاعدة البصمة.'}
          </StatusMessage>
        )}
        <form className="form-grid" onSubmit={saveDatabaseSettings}>
          <label>عنوان خادم قاعدة البصمة
            <input required maxLength="255" value={databaseForm.host} onChange={event => setDatabaseForm({ ...databaseForm, host: event.target.value })} />
          </label>
          <label>منفذ قاعدة البصمة
            <input type="number" min="1" max="65535" required value={databaseForm.port} onChange={event => setDatabaseForm({ ...databaseForm, port: event.target.value })} />
          </label>
          <label>اسم قاعدة البصمة
            <input required maxLength="64" value={databaseForm.attendance_database} onChange={event => setDatabaseForm({ ...databaseForm, attendance_database: event.target.value })} />
          </label>
          <label>مستخدم قاعدة البصمة
            <input required maxLength="100" autoComplete="off" value={databaseForm.attendance_username} onChange={event => setDatabaseForm({ ...databaseForm, attendance_username: event.target.value })} />
          </label>
          <label>كلمة مرور قاعدة البصمة
            <input type="password" maxLength="256" autoComplete="new-password" placeholder={databaseSettings?.attendance_password_set ? 'اتركها فارغة للاحتفاظ بالحالية' : 'أدخل كلمة المرور'} value={databaseForm.attendance_password} onChange={event => setDatabaseForm({ ...databaseForm, attendance_password: event.target.value })} />
          </label>
          <div className="header-controls" style={{ gridColumn: '1 / -1' }}>
            <button type="button" onClick={testDatabaseConnection} disabled={databaseTestBusy || databaseSettingsBusy}>
              {databaseTestBusy ? 'جارٍ اختبار الاتصال…' : 'اختبار الاتصال'}
            </button>
            <button type="submit" disabled={databaseSettingsBusy || databaseTestBusy}>
              {databaseSettingsBusy ? 'جارٍ الحفظ…' : 'حفظ وتطبيق الإعدادات'}
            </button>
          </div>
        </form>
        {databaseTestResult && (
          <div className="analytics-strip" aria-live="polite">
            <p><strong>قاعدة البصمة:</strong> {databaseTestResult.attendance_connected ? 'متصلة' : 'فشل الاتصال'}</p>
          </div>
        )}
      </section>

      <section className="card">
        <div className="section-heading">
          <div><h2>إدارة الموظفين والورديات</h2><p>اجلب الموظفين من قاعدة البصمة، ثم أدِر الورديات والتكليفات محلياً.</p></div>
          <button type="button" onClick={syncEmployees} disabled={employeeSyncBusy || refreshing}>
            {employeeSyncBusy ? 'جارٍ جلب الموظفين…' : 'جلب الموظفين من قاعدة البصمة'}
          </button>
        </div>
        {unassignedEmployees.length > 0 && <StatusMessage kind="warning">{unassignedEmployees.length} موظف نشط غير معيّن حاليًا إلى وردية.</StatusMessage>}
        {!employees.length && !loading && <p className="empty-state">قائمة الموظفين فارغة أو تعذّر تحميلها. {loadError ? 'راجع رسالة الخطأ أعلاه.' : 'أضف موظفًا من النموذج أدناه.'}</p>}
        {employees.length > 0 && (
          <DataTable>
            <thead><tr><th>رقم الموظف</th><th>الاسم</th><th>الحالة</th><th>الوردية والتعيينات</th><th>تاريخ النفاذ</th><th>الإجراءات</th></tr></thead>
            <tbody>{employees.map(employee => {
              const id = String(employeeIdOf(employee));
              const assignment = currentAssignments.get(id);
              const upcomingAssignment = upcomingAssignments.get(id);
              const currentShift = shifts.find(item => String(item.id) === String(shiftIdOf(assignment)));
              const upcomingShift = shifts.find(item => String(item.id) === String(shiftIdOf(upcomingAssignment)));
              const isDeactivated = employee.is_active === false || employee.active === false;
              return <tr key={id}>
                <td data-label="رقم الموظف">{id}</td>
                <td data-label="الاسم">{employeeNameOf(employee) || '—'}</td>
                <td data-label="الحالة"><span className={`badge ${isDeactivated ? 'badge--muted' : 'badge--success'}`}>{isDeactivated ? 'موقوف' : 'نشط'}</span></td>
                <td data-label="الوردية والتعيينات">
                  {assignment && <span className="shift-color"><i style={{ backgroundColor: currentShift?.color || assignment.color || '#94a3b8' }} />حاليًا: {shiftNameForAssignment(assignment)}</span>}
                  {upcomingAssignment && <span className="shift-color"><i style={{ backgroundColor: upcomingShift?.color || upcomingAssignment.color || '#94a3b8' }} />مجدول: {shiftNameForAssignment(upcomingAssignment)} من {upcomingAssignment.start_date || upcomingAssignment.effective_from}</span>}
                  {!assignment && !upcomingAssignment && <span className="badge badge--warning">غير معيّن</span>}
                </td>
                <td data-label="تاريخ النفاذ">حالي: {assignment?.start_date || assignment?.effective_from || '—'}<br />مجدول: {upcomingAssignment?.start_date || upcomingAssignment?.effective_from || '—'}</td>
                <td data-label="الإجراءات">
                  <div className="row-actions">
                    <button type="button" className="button-sm" onClick={() => beginEmployeeEdit(employee)}>تعديل</button>
                    {/* [البند 5] زر تفعيل للموظف الموقوف، وزر إيقاف للموظف النشط */}
                    {isDeactivated ? (
                      <button type="button" className="button-sm button-success" onClick={() => activateEmployee(employee)}>تفعيل</button>
                    ) : (
                      <button type="button" className="button-sm button-secondary" onClick={() => deactivateEmployee(employee)}>إيقاف</button>
                    )}
                  </div>
                </td>
              </tr>;
            })}</tbody>
          </DataTable>
        )}
        <div className="management-grid">
          <form className="card form-card" onSubmit={saveEmployee}>
            <h3>{editingEmployeeId ? 'تعديل موظف' : 'إضافة موظف'}</h3>
            <div className="form-grid">
              <label>رقم الموظف<input value={employeeForm.employee_id} onChange={event => setEmployeeForm({ ...employeeForm, employee_id: event.target.value })} required disabled={Boolean(editingEmployeeId)} /></label>
              <label>اسم الموظف<input value={employeeForm.employee_name} onChange={event => setEmployeeForm({ ...employeeForm, employee_name: event.target.value })} required /></label>
              <button type="submit">حفظ الموظف</button>
              {editingEmployeeId && <button type="button" onClick={() => { setEditingEmployeeId(null); setEmployeeForm({ employee_id: '', employee_name: '' }); }}>إلغاء التعديل</button>}
            </div>
          </form>
          <form className="card form-card" onSubmit={assignShift}>
            <h3>تعيين أو تغيير وردية</h3>
            <div className="form-grid">
              <label>الموظف<select required value={assignmentForm.employee_id} onChange={event => setAssignmentForm({ ...assignmentForm, employee_id: event.target.value })}><option value="">اختر الموظف</option>{activeEmployees.map(employee => <option key={employeeIdOf(employee)} value={employeeIdOf(employee)}>{employeeNameOf(employee) || employeeIdOf(employee)} ({employeeIdOf(employee)})</option>)}</select></label>
              <label>الوردية<select required value={assignmentForm.shift_id} onChange={event => setAssignmentForm({ ...assignmentForm, shift_id: event.target.value })}><option value="">اختر الوردية</option>{shifts.map(shift => <option key={shift.id} value={shift.id}>{shift.name}</option>)}</select></label>
              <label>تاريخ النفاذ<input type="date" required value={assignmentForm.start_date} onChange={event => setAssignmentForm({ ...assignmentForm, start_date: event.target.value })} /></label>
              <button type="submit" disabled={!employees.length || !shifts.length}>حفظ التوزيع</button>
            </div>
          </form>
        </div>

        {/* [البند 4] سجل توزيع الورديات مع زر حذف آخر تكليف */}
        <div style={{ marginBlockStart: '2.5rem' }}>
          <div className="section-heading">
            <div>
              <h3>سجل تكليفات الورديات</h3>
              <p>سجل التكليفات المسجلة للموظفين. يمكنك حذف آخر تكليف تم إدخاله بالخطأ لتصحيحه، وسيتم فتح التكليف السابق تلقائياً إن وجد.</p>
            </div>
          </div>
          {assignments.length === 0 ? (
            <p className="empty-state">لا توجد تكليفات مسجلة للورديات.</p>
          ) : (
            <DataTable>
              <thead>
                <tr>
                  <th>الموظف</th>
                  <th>الوردية</th>
                  <th>تاريخ البداية</th>
                  <th>تاريخ النهاية</th>
                  <th>الحالة</th>
                  <th>الإجراءات</th>
                </tr>
              </thead>
              <tbody>
                {assignments.map(item => {
                  const emp = employees.find(e => String(employeeIdOf(e)) === String(item.employee_id));
                  const empName = emp ? employeeNameOf(emp) : item.employee_id;
                  const isLatest = latestAssignmentIds.has(item.id);
                  const today = attendance?.date || serverToday || todayString();
                  const isUpcoming = item.start_date > today;
                  const isCurrent = item.start_date <= today && (!item.end_date || item.end_date >= today);
                  return (
                    <tr key={item.id}>
                      <td data-label="الموظف">{empName} ({item.employee_id})</td>
                      <td data-label="الوردية">{shiftNameForAssignment(item)}</td>
                      <td data-label="تاريخ البداية">{item.start_date}</td>
                      <td data-label="تاريخ النهاية">{item.end_date || 'مستمر'}</td>
                      <td data-label="الحالة">
                        <span className={`badge ${isUpcoming ? 'badge--warning' : isCurrent ? 'badge--success' : 'badge--muted'}`}>
                          {isUpcoming ? 'مجدول' : isCurrent ? 'حالي' : 'منتهٍ'}
                        </span>
                      </td>
                      <td data-label="الإجراءات">
                        {isLatest ? (
                          <button
                            type="button"
                            className="button-danger button-sm"
                            onClick={() => deleteLastShiftAssignment(item)}
                            title="حذف آخر تكليف وردية للموظف"
                          >
                            حذف آخر تكليف
                          </button>
                        ) : (
                          <span className="badge badge--muted">سابق</span>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </DataTable>
          )}
        </div>
      </section>

      <section className="card">
        <div className="section-heading">
          <div><h2>إدارة الورديات</h2><p>{shifts.length} وردية · {activeShifts.length} نشطة · يمكن ضبط لون الوردية وطريقة احتساب التأخير.</p></div>
          {!shiftFormOpen && <button type="button" onClick={() => beginShiftForm()}>إضافة وردية</button>}
        </div>
        {shifts.length === 0 && !loading && <p className="empty-state">لا توجد ورديات متاحة.</p>}
        <div className="shift-list">
          {shifts.map(shift => <article className="shift-item" key={shift.id}>
            <span className="shift-color"><i style={{ backgroundColor: shift.color || '#94a3b8' }} />{shift.name}</span>
            <span>{timeDisplay(shift.start_time, shift.end_time)}</span>
            <span>سماح {shift.grace_period_minutes ?? 0} دقيقة</span>
            <span>{shift.lateness_mode === 'from_start' ? 'التأخير من بداية الوردية' : 'التأخير بعد السماح'}</span>
            <span className={`badge ${shift.is_active ? 'badge--success' : 'badge--muted'}`}>{shift.is_active ? 'نشطة' : 'غير نشطة'}</span>
            <div className="row-actions"><button type="button" onClick={() => beginShiftForm(shift)}>تعديل</button><button type="button" onClick={() => deleteShift(shift)}>حذف</button></div>
          </article>)}
        </div>
        {shiftFormOpen && (
          <form className="card form-card" onSubmit={saveShift}>
            <h3>{editingShiftId ? 'تعديل وردية' : 'إضافة وردية'}</h3>
            <div className="form-grid">
              <label>اسم الوردية<input required maxLength="100" value={shiftForm.name} onChange={event => setShiftForm({ ...shiftForm, name: event.target.value })} /></label>
              <label>من<input type="time" required value={shiftForm.start_time} onChange={event => setShiftForm({ ...shiftForm, start_time: event.target.value })} /></label>
              <label>إلى<input type="time" required value={shiftForm.end_time} onChange={event => setShiftForm({ ...shiftForm, end_time: event.target.value })} /></label>
              <label>فترة السماح بالدقائق<input type="number" min="0" required value={shiftForm.grace_period_minutes} onChange={event => setShiftForm({ ...shiftForm, grace_period_minutes: event.target.value })} /></label>
              <label>طريقة احتساب التأخير<select value={shiftForm.lateness_mode} onChange={event => setShiftForm({ ...shiftForm, lateness_mode: event.target.value })}><option value="after_grace">بعد فترة السماح</option><option value="from_start">من بداية الوردية</option></select></label>
              <label>لون الوردية<input type="color" value={shiftForm.color} onChange={event => setShiftForm({ ...shiftForm, color: event.target.value })} /></label>
              <label className="checkbox-label"><input type="checkbox" checked={shiftForm.is_active} onChange={event => setShiftForm({ ...shiftForm, is_active: event.target.checked })} /> وردية نشطة</label>
              <button type="submit">حفظ الوردية</button>
              <button type="button" onClick={() => { setEditingShiftId(null); setShiftFormOpen(false); }}>إلغاء</button>
            </div>
          </form>
        )}
      </section>

      <section className="card">
        <h2>نقل الموظفين وسجل الفروع</h2>
        {/* [البند 6] تحسين نموذج نقل الفرع: قائمة منسدلة للموظف واسم معبأ آلياً */}
        <form className="form-grid" onSubmit={transferBranch}>
          <label>
            الموظف
            <select
              required
              value={branchForm.employee_id}
              onChange={event => {
                const id = event.target.value;
                const emp = employees.find(e => String(employeeIdOf(e)) === id);
                setBranchForm(prev => ({
                  ...prev,
                  employee_id: id,
                  employee_name: emp ? (emp.name || emp.employee_name || '') : '',
                }));
              }}
            >
              <option value="">اختر الموظف</option>
              {activeEmployees.map(emp => {
                const id = String(employeeIdOf(emp));
                const name = employeeNameOf(emp);
                return (
                  <option key={id} value={id}>
                    {name ? `${name} (${id})` : id}
                  </option>
                );
              })}
            </select>
          </label>
          <label>
            الاسم الكامل
            <input
              value={branchForm.employee_name}
              onChange={event => setBranchForm({ ...branchForm, employee_name: event.target.value })}
              placeholder="يُملأ تلقائياً عند اختيار الموظف"
            />
          </label>
          <label>
            الفرع الجديد
            <input
              required
              value={branchForm.branch_name}
              onChange={event => setBranchForm({ ...branchForm, branch_name: event.target.value })}
              placeholder="اسم الفرع"
            />
          </label>
          <label>
            تاريخ النقل
            <input
              type="date"
              required
              value={branchForm.start_date}
              onChange={event => setBranchForm({ ...branchForm, start_date: event.target.value })}
            />
          </label>
          <label>
            ملاحظات
            <input
              value={branchForm.notes}
              onChange={event => setBranchForm({ ...branchForm, notes: event.target.value })}
              placeholder="ملاحظات النقل (اختياري)"
            />
          </label>
          <button type="submit" disabled={!branchForm.employee_id || !branchForm.branch_name}>
            حفظ النقل
          </button>
        </form>

        {/* [البند 4] سجل الفروع مع زر حذف آخر نقل */}
        {branchesList.length === 0 ? <p className="empty-state">لا توجد سجلات فروع للعرض.</p> : (
          <DataTable>
            <thead>
              <tr>
                <th>الموظف</th>
                <th>الفرع</th>
                <th>من</th>
                <th>إلى</th>
                <th>ملاحظات</th>
                <th>الإجراءات</th>
              </tr>
            </thead>
            <tbody>{branchesList.map(record => {
              const isLatest = latestBranchRecordIds.has(record.id);
              return (
                <tr key={record.id}>
                  <td data-label="الموظف">{record.employee_name || record.employee_id} ({record.employee_id})</td>
                  <td data-label="الفرع">{record.branch_name}</td>
                  <td data-label="من">{record.start_date}</td>
                  <td data-label="إلى">
                    {record.is_future
                      ? `مجدول من ${record.start_date}`
                      : record.is_current
                        ? 'حالي'
                        : record.end_date || 'سجل تاريخي'}
                  </td>
                  <td data-label="ملاحظات">{record.notes || '—'}</td>
                  <td data-label="الإجراءات">
                    {isLatest ? (
                      <button
                        type="button"
                        className="button-danger button-sm"
                        onClick={() => deleteLastBranchRecord(record)}
                        title="حذف آخر سجل نقل لهذا الموظف"
                      >
                        حذف آخر نقل
                      </button>
                    ) : (
                      <span className="badge badge--muted">سابق</span>
                    )}
                  </td>
                </tr>
              );
            })}</tbody>
          </DataTable>
        )}
      </section>
      </>}
    </main>
  );
}

function MiniTrend({ values }) {
  const points = asList(values);
  if (points.length < 2) return null;
  const numbers = points.map(point => Number(typeof point === 'number' ? point : point.value ?? point.count ?? point.late_minutes ?? 0));
  const max = Math.max(...numbers, 1);
  const coordinates = numbers.map((value, index) => `${(index / (numbers.length - 1)) * 100},${38 - (value / max) * 32}`).join(' ');
  return <div className="trend-chart" aria-label="اتجاه القيم اليومية">
    <svg viewBox="0 0 100 40" role="img" aria-label="مخطط اتجاه يومي">
      <polyline points={coordinates} fill="none" stroke="currentColor" strokeWidth="2" vectorEffect="non-scaling-stroke" />
    </svg>
    <span>اتجاه يومي</span>
  </div>;
}

function EmployeeLateChart({ employees }) {
  const ranked = asList(employees)
    .slice()
    .sort((a, b) => Number(b.total_late_minutes || 0) - Number(a.total_late_minutes || 0))
    .slice(0, 6);
  if (ranked.length === 0) {
    return <p className="empty-state">لا توجد تأخيرات مسجلة في هذه الفترة.</p>;
  }
  const maximum = Math.max(...ranked.map(employee => Number(employee.total_late_minutes || 0)), 1);
  return <div className="employee-chart" role="list" aria-label="أكثر الموظفين تأخراً بالدقائق">
    {ranked.map(employee => {
      const minutes = Number(employee.total_late_minutes || 0);
      return <div className="employee-chart-row" role="listitem" key={employee.employee_id}>
        <span className="employee-chart-name" title={employee.employee_name || employee.employee_id}>{employee.employee_name || `موظف ${employee.employee_id}`}</span>
        <span className="employee-chart-track" aria-hidden="true"><span className="employee-chart-fill" style={{ width: `${Math.max((minutes / maximum) * 100, 1)}%` }} /></span>
        <span className="employee-chart-value">{minutes} د</span>
      </div>;
    })}
  </div>;
}
