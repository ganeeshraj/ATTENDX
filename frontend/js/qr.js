const getPos=()=>new Promise((ok,no)=>navigator.geolocation?navigator.geolocation.getCurrentPosition(p=>ok(p.coords),()=>no(new Error('Location permission is required')),{enableHighAccuracy:true,timeout:15000}):no(new Error('Geolocation not supported')));
initPage('qr',async(u,m)=>{
  if(u.role==='faculty'){
    m.innerHTML=`<div class="panel"><label>Subject<input id="subj" placeholder="e.g. Data Structures"></label><br><button class="btn" id="mk">Create Attendance Session</button>
    <p><small>Start time is automatic · You will enter only the Close Time · Late after 15 minutes · Radius 100 m</small></p><div id="out"></div></div>`;
    $('mk').onclick=async()=>{try{
      const closeTime=window.prompt('Enter Session Close Time (24-hour HH:MM):','10:00');
      if(closeTime===null)return;
      if(!/^([01]\d|2[0-3]):[0-5]\d$/.test(closeTime)){throw new Error('Enter close time in HH:MM format, for example 10:00');}
      const p=await getPos();
      const s=(await api('/sessions',{method:'POST',body:{subject:$('subj').value,lat:p.latitude,lng:p.longitude,close_time:closeTime}})).session;
      $('out').innerHTML=`<div class="msg ok">Session created for <b>${esc(s.subject)}</b>. Students can scan this QR.</div><div id="qrbox"></div>`;
      new QRCode($('qrbox'),{text:s.token,width:240,height:240});
      const closeLabel=s.close_at ? new Date('1970-01-01T'+s.close_at+'Z').toLocaleTimeString([], {hour:'2-digit',minute:'2-digit'}) : closeTime;
      $('out').insertAdjacentHTML('afterbegin',`<div class="msg ok">Session Start: <b>Now</b> · Close Time: <b>${esc(closeLabel)}</b></div>`);
      const closeParts=(s.close_at||closeTime).split(':').map(Number);
      const stopAt=new Date(); stopAt.setHours(closeParts[0],closeParts[1],0,0);
      const timer=setInterval(()=>{ if(Date.now()>=stopAt.getTime()){clearInterval(timer); $('qrbox').innerHTML=''; $('out').insertAdjacentHTML('beforeend','<div class="msg err">QR session closed automatically.</div>'); $('mk').disabled=false;} },1000);
      $('mk').disabled=true;
    }catch(e){$('out').innerHTML=`<div class="msg err">${esc(e.message)}</div>`}};
  }else{
    m.innerHTML=`<div class="panel"><div id="reader" style="max-width:360px;margin:auto"></div><div id="res"></div></div>`;
    let busy=false;const sc=new Html5Qrcode('reader');
    const done=(h,ok)=>$('res').innerHTML=`<div class="msg ${ok?'ok':'err'}">${h}</div>`;
    sc.start({facingMode:'environment'},{fps:10,qrbox:240},async token=>{
      if(busy)return;busy=true;
      try{const p=await getPos();const r=await api('/attendance/scan',{method:'POST',body:{token,lat:p.latitude,lng:p.longitude}});
        done(`✔ ${r.message} — ${esc(r.subject)} (${r.status}, ${r.distance} m away)`,true);sc.stop().catch(()=>{})}
      catch(e){done('✖ Attendance Failed: '+esc(e.message),false);setTimeout(()=>busy=false,3000)}
    }).catch(()=>done('Camera could not start. Allow camera access (use HTTPS or localhost).',false));
  }
});
