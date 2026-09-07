"""Write a self-contained WebGL viewer for the extracted world.

    python3 viewer.py rd_world_viewer.html

No network, no libraries, no ROM data beyond the geometry you extracted from
your own dumps. Open the file in any browser.
"""
import base64, json, struct, sys, os
import world

OVERLAYS = {"DOTLINE", "DOTLHALF", "GRDARROW", "FINISH", "SORS", "CHKPT",
            "STRTPOST", "XOVER", "TURNOFF", "SKIDPAD"}


def build(path):
    w = world.World()
    pal = open("rd_palette.bin", "rb").read()
    pos, col, objs = [], [], []
    for r in range(world.PLACE_N):
        p = w.placement(r)
        mo = w.model(p["obj"])
        if not mo or not mo["faces"]:
            continue
        # Road markings are authored at exactly the pavement's Y, which the
        # real hardware resolved by draw order. A depth buffer cannot, so lift
        # them a few units here. Display only - the exported OBJ is untouched.
        lift = 4 if p["name"] in OVERLAYS else 0
        t = (p["x"], p["y"] + lift, p["z"])
        V = [world.transform(v, p["m"], t) for v in mo["verts"]]
        start = len(pos) // 3
        for idx, c in mo["faces"]:
            for k in range(1, len(idx) - 1):          # fan-triangulate
                for i in (idx[0], idx[k], idx[k + 1]):
                    pos.extend(V[i]); col.append(c)
        objs.append({"n": r, "name": p["name"], "obj": p["obj"],
                     "s": start, "c": len(pos) // 3 - start,
                     "p": [p["x"], p["y"], p["z"]]})
    xs = pos[0::3]; ys = pos[1::3]; zs = pos[2::3]
    bounds = [min(xs), min(ys), min(zs), max(xs), max(ys), max(zs)]
    P = base64.b64encode(struct.pack("<%df" % len(pos), *pos)).decode()
    C = base64.b64encode(bytes(col)).decode()
    PAL = base64.b64encode(pal).decode()
    html = TEMPLATE.replace("__POS__", P).replace("__COL__", C) \
                   .replace("__PAL__", PAL) \
                   .replace("__OBJS__", json.dumps(objs, separators=(",", ":"))) \
                   .replace("__BOUNDS__", json.dumps(bounds)) \
                   .replace("__NTRI__", str(len(col) // 3))
    open(path, "w").write(html)
    return len(col) // 3, len(objs), os.path.getsize(path)

TEMPLATE = r"""<!doctype html>
<html><head><meta charset="utf-8"><title>Race Drivin' World</title>
<style>
  :root{--ink:#e8e6e1;--dim:#8a8780;--rule:#2a2d33;--bg:#0e1014;--panel:#161920;--hi:#e0b341}
  *{box-sizing:border-box}
  html,body{margin:0;height:100%;overflow:hidden;background:var(--bg);color:var(--ink);
    font:13px/1.5 ui-monospace,SFMono-Regular,Menlo,monospace}
  canvas{display:block;width:100%;height:100%;cursor:grab}
  canvas.drag{cursor:grabbing}
  #ui{position:fixed;top:0;left:0;padding:14px 16px;pointer-events:none;
      text-shadow:0 1px 3px #000}
  #ui h1{margin:0 0 2px;font-size:14px;font-weight:600;letter-spacing:.02em}
  #ui p{margin:0;color:var(--dim);font-size:11px}
  #panel{position:fixed;top:14px;right:14px;width:210px;background:var(--panel);
    border:1px solid var(--rule);border-radius:6px;padding:10px 12px}
  .row{display:flex;gap:6px;flex-wrap:wrap;margin-bottom:8px}
  button{flex:1;min-width:56px;background:#1e222b;color:var(--ink);border:1px solid var(--rule);
    border-radius:4px;padding:5px 6px;font:inherit;font-size:11px;cursor:pointer}
  button:hover{border-color:var(--hi);color:var(--hi)}
  button.on{background:var(--hi);color:#14161a;border-color:var(--hi)}
  label{display:block;color:var(--dim);font-size:10px;letter-spacing:.08em;
    text-transform:uppercase;margin:10px 0 4px}
  #list{max-height:38vh;overflow:auto;border-top:1px solid var(--rule);margin-top:8px;padding-top:6px}
  #list div{padding:2px 4px;border-radius:3px;cursor:pointer;color:var(--dim);
    white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
  #list div:hover{background:#1e222b;color:var(--ink)}
  #hint{position:fixed;bottom:12px;left:16px;color:var(--dim);font-size:11px}
</style></head><body>
<canvas id="c"></canvas>
<div id="ui"><h1>Race Drivin&rsquo; &mdash; static world</h1>
<p>__NTRI__ triangles &middot; <span id="nobj"></span> objects &middot; 2.06 &times; 1.53 km</p></div>
<div id="panel">
  <div class="row"><button id="vTop">Top</button><button id="vPersp">3/4</button>
    <button id="vGround">Ground</button></div>
  <label>Palette bank</label>
  <div class="row" id="banks"></div>
  <label>Find</label>
  <div id="list"></div>
</div>
<div id="hint">drag orbit &middot; wheel zoom &middot; shift-drag pan</div>
<script>
const B64=s=>{const b=atob(s),u=new Uint8Array(b.length);
  for(let i=0;i<b.length;i++)u[i]=b.charCodeAt(i);return u};
const POS=new Float32Array(B64("__POS__").buffer);
const COL=B64("__COL__"), PAL=B64("__PAL__");
const OBJS=__OBJS__, BB=__BOUNDS__;
document.getElementById('nobj').textContent=OBJS.length;

const cx=(BB[0]+BB[3])/2, cy=(BB[1]+BB[4])/2, cz=(BB[2]+BB[5])/2;
const span=Math.max(BB[3]-BB[0],BB[5]-BB[2]);
const P=new Float32Array(POS.length);
for(let i=0;i<POS.length;i+=3){P[i]=(POS[i]-cx)/span;P[i+1]=(POS[i+1]-cy)/span;P[i+2]=(POS[i+2]-cz)/span}

const cv=document.getElementById('c');
const gl=cv.getContext('webgl2',{antialias:true});
const vs=`#version 300 es
in vec3 p; in float ci; uniform mat4 mvp; out vec3 w; flat out float vi;
void main(){w=p; vi=ci; gl_Position=mvp*vec4(p,1.0);}`;
const fs=`#version 300 es
precision highp float; in vec3 w; flat in float vi; uniform sampler2D pal;
uniform float bank; out vec4 o;
void main(){
  vec3 n=normalize(cross(dFdx(w),dFdy(w)));
  float l=0.42+0.58*abs(dot(n,normalize(vec3(0.45,0.82,0.35))));
  vec3 c=texelFetch(pal,ivec2(int(vi),int(bank)),0).rgb;
  o=vec4(c*l,1.0);}`;
function sh(t,s){const x=gl.createShader(t);gl.shaderSource(x,s);gl.compileShader(x);
  if(!gl.getShaderParameter(x,gl.COMPILE_STATUS))throw gl.getShaderInfoLog(x);return x}
const pr=gl.createProgram();
gl.attachShader(pr,sh(gl.VERTEX_SHADER,vs));gl.attachShader(pr,sh(gl.FRAGMENT_SHADER,fs));
gl.linkProgram(pr);gl.useProgram(pr);

const vb=gl.createBuffer();gl.bindBuffer(gl.ARRAY_BUFFER,vb);
gl.bufferData(gl.ARRAY_BUFFER,P,gl.STATIC_DRAW);
const ap=gl.getAttribLocation(pr,'p');gl.enableVertexAttribArray(ap);
gl.vertexAttribPointer(ap,3,gl.FLOAT,false,0,0);
const cb=gl.createBuffer();gl.bindBuffer(gl.ARRAY_BUFFER,cb);
gl.bufferData(gl.ARRAY_BUFFER,Float32Array.from(COL),gl.STATIC_DRAW);
const ac=gl.getAttribLocation(pr,'ci');gl.enableVertexAttribArray(ac);
gl.vertexAttribPointer(ac,1,gl.FLOAT,false,0,0);

const tex=gl.createTexture();gl.activeTexture(gl.TEXTURE0);gl.bindTexture(gl.TEXTURE_2D,tex);
const rgba=new Uint8Array(256*8*4);
for(let i=0;i<2048;i++){rgba[i*4]=PAL[i*3];rgba[i*4+1]=PAL[i*3+1];rgba[i*4+2]=PAL[i*3+2];rgba[i*4+3]=255}
gl.texImage2D(gl.TEXTURE_2D,0,gl.RGBA,256,8,0,gl.RGBA,gl.UNSIGNED_BYTE,rgba);
gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_MIN_FILTER,gl.NEAREST);
gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_MAG_FILTER,gl.NEAREST);
gl.uniform1i(gl.getUniformLocation(pr,'pal'),0);
const uMVP=gl.getUniformLocation(pr,'mvp'), uBank=gl.getUniformLocation(pr,'bank');
gl.enable(gl.DEPTH_TEST);gl.clearColor(0.055,0.063,0.078,1);

let yaw=-0.6, pitch=0.62, dist=1.15, bank=0;
let tg=[0,0,0];
function mul(a,b){const o=new Float32Array(16);
  for(let i=0;i<4;i++)for(let j=0;j<4;j++){let s=0;
    for(let k=0;k<4;k++)s+=a[k*4+j]*b[i*4+k];o[i*4+j]=s}return o}
function basis(){
  const cp=Math.cos(pitch),sp=Math.sin(pitch);
  const dir=[cp*Math.sin(yaw),sp,cp*Math.cos(yaw)];          // target -> eye
  const eye=[tg[0]+dist*dir[0],tg[1]+dist*dir[1],tg[2]+dist*dir[2]];
  const f=[-dir[0],-dir[1],-dir[2]];                          // eye -> target
  let s=[f[1]*0-f[2]*1, f[2]*0-f[0]*0, f[0]*1-f[1]*0];
  const sl=Math.hypot(s[0],s[1],s[2])||1e-6; s=s.map(v=>v/sl);
  const u=[s[1]*f[2]-s[2]*f[1], s[2]*f[0]-s[0]*f[2], s[0]*f[1]-s[1]*f[0]];
  return {eye,f,s,u};
}
function draw(){
  const dpr=Math.min(devicePixelRatio,2);
  cv.width=innerWidth*dpr;cv.height=innerHeight*dpr;
  gl.viewport(0,0,cv.width,cv.height);gl.clear(gl.COLOR_BUFFER_BIT|gl.DEPTH_BUFFER_BIT);
  const fv=1/Math.tan(0.42), a=cv.width/cv.height, n=0.002, fr=40;
  const proj=new Float32Array([fv/a,0,0,0, 0,fv,0,0, 0,0,(fr+n)/(n-fr),-1, 0,0,2*fr*n/(n-fr),0]);
  const {eye,f,s,u}=basis();
  const d=(p,q)=>p[0]*q[0]+p[1]*q[1]+p[2]*q[2];
  const view=new Float32Array([
    s[0],u[0],-f[0],0,  s[1],u[1],-f[1],0,  s[2],u[2],-f[2],0,
    -d(s,eye),-d(u,eye),d(f,eye),1]);
  gl.uniformMatrix4fv(uMVP,false,mul(proj,view));
  gl.uniform1f(uBank,bank);
  gl.drawArrays(gl.TRIANGLES,0,P.length/3);
}
let dragging=false,shift=false,lx=0,ly=0;
cv.addEventListener('mousedown',e=>{dragging=true;shift=e.shiftKey;lx=e.clientX;ly=e.clientY;
  cv.classList.add('drag')});
addEventListener('mouseup',()=>{dragging=false;cv.classList.remove('drag')});
addEventListener('mousemove',e=>{if(!dragging)return;
  const dx=e.clientX-lx,dy=e.clientY-ly;lx=e.clientX;ly=e.clientY;
  if(shift){const {s,u}=basis(),k=dist*0.0016;
    for(let i=0;i<3;i++)tg[i]+=(-s[i]*dx+u[i]*dy)*k;}
  else{yaw-=dx*0.006;pitch=Math.max(-1.45,Math.min(1.45,pitch+dy*0.006))}draw()},{passive:true});
cv.addEventListener('wheel',e=>{e.preventDefault();
  dist=Math.max(0.008,Math.min(8,dist*Math.exp(e.deltaY*0.0016)));draw()},{passive:false});
addEventListener('resize',draw);

const V={vTop:[0,1.44,1.05],vPersp:[-0.6,0.62,1.15],vGround:[-0.6,0.06,0.20]};
for(const k in V)document.getElementById(k).onclick=()=>{
  [yaw,pitch,dist]=V[k];tg=[0,0,0];draw()};
const bw=document.getElementById('banks');
for(let b=0;b<8;b++){const x=document.createElement('button');x.textContent=b;
  if(b===bank)x.className='on';x.onclick=()=>{bank=b;
    [...bw.children].forEach(c=>c.className='');x.className='on';draw()};bw.appendChild(x)}

const seen={},L=document.getElementById('list');
OBJS.forEach(o=>{(seen[o.name]=seen[o.name]||[]).push(o)});
let cyc={};
Object.keys(seen).sort().forEach(nm=>{const d=document.createElement('div');
  const list=seen[nm];
  d.textContent=nm+(list.length>1?'  ×'+list.length:'');
  d.onclick=()=>{const i=(cyc[nm]=((cyc[nm]??-1)+1)%list.length), o=list[i];
    tg=[(o.p[0]-cx)/span,(o.p[1]-cy)/span,(o.p[2]-cz)/span];
    pitch=0.30; dist=0.045; draw();
    d.style.color='var(--hi)'; setTimeout(()=>d.style.color='',700);};
  L.appendChild(d)});
draw();
</script></body></html>
"""

if __name__ == "__main__":
    out = sys.argv[1] if len(sys.argv) > 1 else "rd_world_viewer.html"
    n, o, sz = build(out)
    print("wrote %s: %d triangles, %d objects, %.1f MB" % (out, n, o, sz / 1e6))
