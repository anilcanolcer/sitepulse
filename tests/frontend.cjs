const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
const root=path.resolve(__dirname,'..');
const html=fs.readFileSync(path.join(root,'frontend/index.html'),'utf8');
const inline=[...html.matchAll(/<script>([\s\S]*?)<\/script>/g)].map(m=>m[1]).join('\n');
const stored=new Map([['sitepulse-theme','dark']]);const classes=new Set();
const context={localStorage:{getItem:k=>stored.get(k),setItem:(k,v)=>stored.set(k,v)},document:{documentElement:{classList:{toggle:(k,on)=>on?classes.add(k):classes.delete(k),remove:k=>classes.delete(k)}}},setTimeout,clearTimeout};
let polling=null,cleared=false;
context.setInterval=fn=>{polling=fn;return 1};context.clearInterval=()=>{cleared=true};
vm.createContext(context);
vm.runInContext(fs.readFileSync(path.join(root,'frontend/assets/theme-init.js'),'utf8'),context);
assert(classes.has('dark'),'Saved dark preference must apply before rendering');
vm.runInContext(inline+';globalThis.app=dashboard()',context);const app=context.app;
assert.equal(app.theme,'dark');app.toggleTheme();assert.equal(stored.get('sitepulse-theme'),'light');assert(!classes.has('dark'));
app.toggleTheme();assert.equal(stored.get('sitepulse-theme'),'dark');assert(classes.has('dark'));
vm.runInContext('globalThis.reopened=dashboard()',context);assert.equal(context.reopened.theme,'dark');
app.lang='tr';assert.equal(app.t('lightTheme'),'Açık temaya geç');app.lang='en';assert.equal(app.t('darkTheme'),'Switch to dark theme');
assert.equal(app.daysLeft(null),'Unknown');assert.equal(app.daysLeft('2000-01-01'),'Expired');
assert.equal(app.expiryClass('2000-01-01'),'text-rose-600');
assert.equal(app.scoreClass(90),'text-emerald-700');assert.equal(app.scoreClass(30),'text-rose-600');
app.data.sites=[{id:1,client_name:'Example',http_status:200,hosting_expires_at:'2000-01-01'}];assert.equal(app.alerts()[0].type,'hostingExpired');
async function checkLifecycle(){
  let loads=0;app.load=()=>{loads++};app.api=async()=>({enabled:false});await app.init();assert.equal(loads,1);polling();assert.equal(loads,2);app.busy=true;polling();assert.equal(loads,2);app.destroy();assert(cleared);
  const saved=[];app.api=async(path,options)=>{saved.push(JSON.parse(options.body));return {saved:true}};app.desktopPrefs=true;app.toggleTheme();assert.equal(saved.length,1);assert.equal(saved[0].theme,app.theme);
  console.log('Theme persistence, localization, polling, countdowns, hosting alerts, and score states passed');
}
checkLifecycle().catch(error=>{console.error(error);process.exitCode=1});
