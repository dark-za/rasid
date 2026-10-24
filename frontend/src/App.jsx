import React, { useState, useEffect } from 'react';

export default function App() {
  const [attendance, setAttendance] = useState(null);
  const [shifts, setShifts] = useState([]);
  const [branches, setBranches] = useState({ items: [], total: 0 });
  
  // Form states for branch transfer
  const [empId, setEmpId] = useState('');
  const [empName, setEmpName] = useState('');
  const [branchName, setBranchName] = useState('');
  const [startDate, setStartDate] = useState('');
  const [notes, setNotes] = useState('');
  const [apiKey, setApiKey] = useState(() => localStorage.getItem('rasid-api-key') || '');
  const [apiError, setApiError] = useState('');

  const apiFetch = (path, options = {}) => fetch(path, {
    ...options,
    headers: { ...options.headers, 'X-API-Key': apiKey }
  });

  const fetchData = async () => {
    const errors = [];
    const readEndpoint = async (path, label, setter) => {
      try {
        const response = await apiFetch(path);
        const body = await response.json().catch(() => ({}));
        if (!response.ok) throw new Error(body.detail || `تعذر تحميل ${label}`);
        setter(body);
      } catch (err) {
        errors.push(`${label}: ${err.message}`);
      }
    };

    await Promise.all([
      readEndpoint('/api/attendance/today', 'الحضور', setAttendance),
      readEndpoint('/api/shifts', 'الشيفتات', setShifts),
      readEndpoint('/api/employee-branches?limit=200', 'سجل الفروع', setBranches),
    ]);
    setApiError(errors.join(' | '));
  };

  useEffect(() => {
    fetchData();
  }, []);

  const handleAssignBranch = async (e) => {
    e.preventDefault();
    try {
      const res = await apiFetch('/api/employee-branches', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          employee_id: empId,
          employee_name: empName || null,
          branch_name: branchName,
          start_date: startDate,
          notes: notes || null
        })
      });
      if (res.ok) {
        alert('تم تعيين/نقل الموظف للفرع بنجاح');
        setEmpId('');
        setEmpName('');
        setBranchName('');
        setStartDate('');
        setNotes('');
        fetchData();
      } else {
        const body = await res.json().catch(() => ({}));
        alert(body.detail || 'حدث خطأ أثناء الحفظ');
      }
    } catch (err) {
      console.error(err);
    }
  };

  return (
    <div style={{ fontFamily: 'Tahoma, sans-serif', direction: 'rtl', padding: '20px', backgroundColor: '#f4f7f6', minHeight: '100vh' }}>
      <section style={{ background: '#fff', padding: '12px 16px', borderRadius: '8px', marginBottom: '16px' }}>
        <label htmlFor="api-key">مفتاح الوصول: </label>
        <input id="api-key" type="password" value={apiKey} onChange={e => { setApiKey(e.target.value); localStorage.setItem('rasid-api-key', e.target.value); }} autoComplete="current-password" />
        <button type="button" onClick={fetchData} style={{ marginRight: '8px' }}>اتصال</button>
        {apiError && <p role="alert" style={{ color: '#c0392b' }}>{apiError}</p>}
      </section>
      <header style={{ backgroundColor: '#2c3e50', padding: '15px 25px', borderRadius: '8px', marginBottom: '20px', color: '#fff' }}>
        <h1 style={{ margin: 0, fontSize: '24px' }}>نظام راصد (متابعة حضور وانصراف الموظفين)</h1>
        <p style={{ margin: '5px 0 0', fontSize: '14px', color: '#bdc3c7' }}>الربط الحي مع قاعدة بيانات البصمة SmartPSS</p>
      </header>

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '20px' }}>
        
        {/* ملخص الحضور والمتأخرين */}
        <div style={{ background: '#fff', padding: '20px', borderRadius: '8px', boxShadow: '0 2px 4px rgba(0,0,0,0.1)' }}>
          <h2 style={{ color: '#2c3e50', fontSize: '18px', borderBottom: '2px solid #ecf0f1', paddingBottom: '10px' }}>حضور اليوم والمتأخرون</h2>
          {attendance ? (
            <div>
              <p><strong>التاريخ:</strong> {attendance.date}</p>
              <p><strong>إجمالي الحركات (بعد فلترة التبصيم المتكرر &lt; 5 دقائق):</strong> {attendance.total_records_processed}</p>
              
              <h3 style={{ color: '#e74c3c', fontSize: '16px', marginTop: '15px' }}>الموظفون المتأخرون اليوم:</h3>
              {attendance.late_employees.length === 0 ? (
                <p style={{ color: '#27ae60' }}>لا توجد حالات تأخير مسجلة اليوم.</p>
              ) : (
                <table style={{ width: '100%', borderCollapse: 'collapse', marginTop: '10px' }}>
                  <thead>
                    <tr style={{ background: '#f8f9fa', borderBottom: '1px solid #ddd' }}>
                      <th style={{ padding: '8px', textAlign: 'right' }}>رقم الموظف</th>
                      <th style={{ padding: '8px', textAlign: 'right' }}>وقت الحضور</th>
                      <th style={{ padding: '8px', textAlign: 'right' }}>التأخير (بالدقائق)</th>
                    </tr>
                  </thead>
                  <tbody>
                    {attendance.late_employees.map((emp, idx) => (
                      <tr key={idx} style={{ borderBottom: '1px solid #eee' }}>
                        <td style={{ padding: '8px' }}>{emp.employee_id}</td>
                        <td style={{ padding: '8px' }}>{emp.arrival_time}</td>
                        <td style={{ padding: '8px', color: '#e74c3c', fontWeight: 'bold' }}>{emp.late_minutes} دقيقة</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>
          ) : (
            <p>{apiError || 'جاري التحميل...'}</p>
          )}
        </div>

        {/* أساسيات الشيفتات وتوزيع الفروع */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>
          
          <div style={{ background: '#fff', padding: '20px', borderRadius: '8px', boxShadow: '0 2px 4px rgba(0,0,0,0.1)' }}>
            <h2 style={{ color: '#2c3e50', fontSize: '18px', borderBottom: '2px solid #ecf0f1', paddingBottom: '10px' }}>إدارة الشيفتات الأساسية</h2>
            {shifts.map(shift => (
              <div key={shift.id} style={{ background: '#f8f9fa', padding: '10px 15px', borderRadius: '6px', marginTop: '10px' }}>
                <strong>{shift.name}</strong>: من {shift.start_time} إلى {shift.end_time} (فترة السماح: {shift.grace_period_minutes} دقيقة)
              </div>
            ))}
          </div>

          <div style={{ background: '#fff', padding: '20px', borderRadius: '8px', boxShadow: '0 2px 4px rgba(0,0,0,0.1)' }}>
            <h2 style={{ color: '#2c3e50', fontSize: '18px', borderBottom: '2px solid #ecf0f1', paddingBottom: '10px' }}>نقل وتوزيع الموظفين على الفروع</h2>
            <form onSubmit={handleAssignBranch} style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '10px', marginTop: '10px' }}>
              <input type="text" placeholder="رقم الموظف" value={empId} onChange={e => setEmpId(e.target.value)} required style={{ padding: '8px', borderRadius: '4px', border: '1px solid #ccc' }} />
              <input type="text" placeholder="اسم الموظف" value={empName} onChange={e => setEmpName(e.target.value)} style={{ padding: '8px', borderRadius: '4px', border: '1px solid #ccc' }} />
              <input type="text" placeholder="اسم الفرع الجديد" value={branchName} onChange={e => setBranchName(e.target.value)} required style={{ padding: '8px', borderRadius: '4px', border: '1px solid #ccc' }} />
              <input type="date" value={startDate} onChange={e => setStartDate(e.target.value)} required style={{ padding: '8px', borderRadius: '4px', border: '1px solid #ccc' }} />
              <input type="text" placeholder="ملاحظات (اختياري)" value={notes} onChange={e => setNotes(e.target.value)} style={{ gridColumn: 'span 2', padding: '8px', borderRadius: '4px', border: '1px solid #ccc' }} />
              <button type="submit" style={{ gridColumn: 'span 2', background: '#27ae60', color: '#fff', border: 'none', padding: '10px', borderRadius: '4px', cursor: 'pointer', fontWeight: 'bold' }}>حفظ ونقل الفرع</button>
            </form>
          </div>

        </div>

      </div>

      {/* سجل التنقلات بين الفروع */}
      <div style={{ background: '#fff', padding: '20px', borderRadius: '8px', boxShadow: '0 2px 4px rgba(0,0,0,0.1)', marginTop: '20px' }}>
        <h2 style={{ color: '#2c3e50', fontSize: '18px', borderBottom: '2px solid #ecf0f1', paddingBottom: '10px' }}>السجل التاريخي لتنقلات الفروع للموظفين</h2>
        <p style={{ color: '#7f8c8d', fontSize: '13px' }}>إجمالي السجلات: {branches.total}</p>
        <table style={{ width: '100%', borderCollapse: 'collapse', marginTop: '10px' }}>
          <thead>
            <tr style={{ background: '#f8f9fa', borderBottom: '1px solid #ddd' }}>
              <th style={{ padding: '8px', textAlign: 'right' }}>رقم الموظف</th>
              <th style={{ padding: '8px', textAlign: 'right' }}>اسم الموظف</th>
              <th style={{ padding: '8px', textAlign: 'right' }}>الفرع الحالي/السابق</th>
              <th style={{ padding: '8px', textAlign: 'right' }}>من تاريخ</th>
              <th style={{ padding: '8px', textAlign: 'right' }}>إلى تاريخ</th>
              <th style={{ padding: '8px', textAlign: 'right' }}>ملاحظات</th>
            </tr>
          </thead>
          <tbody>
            {branches.items.map(b => (
              <tr key={b.id} style={{ borderBottom: '1px solid #eee' }}>
                <td style={{ padding: '8px' }}>{b.employee_id}</td>
                <td style={{ padding: '8px' }}>{b.employee_name || '-'}</td>
                <td style={{ padding: '8px' }}><strong>{b.branch_name}</strong></td>
                <td style={{ padding: '8px' }}>{b.start_date}</td>
                <td style={{ padding: '8px' }}>{b.end_date || 'حتى الآن (نشط)'}</td>
                <td style={{ padding: '8px' }}>{b.notes || '-'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

    </div>
  );
}
