"""Wrap any OBJ+MTL in a self-contained WebGL page.

    python3 obj_viewer.py vir_world.obj vir_viewer.html
"""
import base64, json, os, struct, sys

def load(path):
    mats, cur, V, tris, cols, objs = {}, (0.7,0.7,0.7), [], [], [], []
    mtl = None
    for line in open(path):
        w = line.split()
        if not w: continue
        if w[0] == "mtllib": mtl = os.path.join(os.path.dirname(path) or ".", w[1])
        elif w[0] == "v": V.append((float(w[1]), float(w[2]), float(w[3])))
        elif w[0] == "o": objs.append({"name": w[1], "start": len(tris)})
        elif w[0] == "usemtl": cur = w[1]
        elif w[0] == "f":
            idx = [int(p.split("/")[0]) - 1 for p in w[1:]]
            for k in range(1, len(idx) - 1):
                tris.append((idx[0], idx[k], idx[k+1])); cols.append(cur)
    if mtl and os.path.exists(mtl):
        name = None
        for line in open(mtl):
            w = line.split()
            if not w: continue
            if w[0] == "newmtl": name = w[1]
            elif w[0] == "Kd" and name:
                mats[name] = (float(w[1]), float(w[2]), float(w[3]))
    return V, tris, cols, mats, objs

def build(objpath, out):
    V, tris, cols, mats, objs = load(objpath)
    pos, rgb = [], []
    for t, c in zip(tris, cols):
        col = mats.get(c, (0.7, 0.7, 0.7))
        for i in t:
            pos.extend(V[i]); rgb.extend(int(v * 255) for v in col)
    for i, o in enumerate(objs):
        e = objs[i+1]["start"] if i+1 < len(objs) else len(tris)
        c = [0.0, 0.0, 0.0]
        for t in tris[o["start"]:e]:
            for k in t:
                for a in range(3): c[a] += V[k][a]
        m = max(1, (e - o["start"]) * 3)
        o["p"] = [v / m for v in c]
    P = base64.b64encode(struct.pack("<%df" % len(pos), *pos)).decode()
    C = base64.b64encode(bytes(rgb)).decode()
    html = TEMPLATE.replace("__POS__", P).replace("__RGB__", C) \
        .replace("__OBJS__", json.dumps([{"name": o["name"], "p": o["p"]} for o in objs],
                                        separators=(",", ":"))) \
        .replace("__NTRI__", str(len(tris))) \
        .replace("__TITLE__", os.environ.get("VIEW_TITLE",
                 os.path.basename(objpath).replace(".obj", ""))) \
        .replace("__SUB__", os.environ.get("VIEW_SUB", "%d objects" % len(objs)))
    open(out, "w").write(html)
    return len(tris), len(objs), os.path.getsize(out)

TEMPLATE = r"""<!doctype html><html><head><meta charset="utf-8">
<title>__TITLE__</title><style>
:root{--ink:#e8e6e1;--dim:#8a8780;--rule:#2a2d33;--bg:#0d1013;--panel:#161920;--hi:#e0b341}
*{box-sizing:border-box}html,body{margin:0;height:100%;overflow:hidden;background:var(--bg);
color:var(--ink);font:13px/1.5 ui-monospace,SFMono-Regular,Menlo,monospace}
canvas{display:block;width:100%;height:100%;cursor:grab}canvas.drag{cursor:grabbing}
#ui{position:fixed;top:0;left:0;padding:14px 16px;pointer-events:none;text-shadow:0 1px 3px #000}
#ui h1{margin:0 0 2px;font-size:14px;font-weight:600}#ui p{margin:0;color:var(--dim);font-size:11px}
#panel{position:fixed;top:14px;right:14px;width:200px;background:var(--panel);
border:1px solid var(--rule);border-radius:6px;padding:10px 12px}
.row{display:flex;gap:6px;margin-bottom:6px}
button{flex:1;background:#1e222b;color:var(--ink);border:1px solid var(--rule);border-radius:4px;
padding:5px 6px;font:inherit;font-size:11px;cursor:pointer}
button:hover{border-color:var(--hi);color:var(--hi)}
label{display:block;color:var(--dim);font-size:10px;letter-spacing:.08em;text-transform:uppercase;
margin:10px 0 4px}#list{max-height:52vh;overflow:auto;border-top:1px solid var(--rule);padding-top:6px}
#list div{padding:2px 4px;border-radius:3px;cursor:pointer;color:var(--dim)}
#list div:hover{background:#1e222b;color:var(--ink)}
#hint{position:fixed;bottom:12px;left:16px;color:var(--dim);font-size:11px}
</style></head><body><canvas id="c"></canvas>
<div id="ui"><h1>__TITLE__</h1>
<p>__NTRI__ triangles &middot; __SUB__</p></div>
<div id="panel"><div class="row"><button id="vTop">Top</button><button id="vPersp">3/4</button>
<button id="vGround">Ground</button></div><label>Go to</label><div id="list"></div></div>
<div id="hint">drag orbit &middot; wheel zoom &middot; shift-drag pan</div><script>
const B64=s=>{const b=atob(s),u=new Uint8Array(b.length);for(let i=0;i<b.length;i++)u[i]=b.charCodeAt(i);return u};
const POS=new Float32Array(B64("__POS__").buffer),RGB=B64("__RGB__"),OBJS=__OBJS__;
let mnx=1e9,mny=1e9,mnz=1e9,mxx=-1e9,mxy=-1e9,mxz=-1e9;
for(let i=0;i<POS.length;i+=3){mnx=Math.min(mnx,POS[i]);mxx=Math.max(mxx,POS[i]);
 mny=Math.min(mny,POS[i+1]);mxy=Math.max(mxy,POS[i+1]);mnz=Math.min(mnz,POS[i+2]);mxz=Math.max(mxz,POS[i+2]);}
const cx=(mnx+mxx)/2,cy=(mny+mxy)/2,cz=(mnz+mxz)/2,span=Math.max(mxx-mnx,mxz-mnz);
const P=new Float32Array(POS.length);
for(let i=0;i<POS.length;i+=3){P[i]=(POS[i]-cx)/span;P[i+1]=(POS[i+1]-cy)/span;P[i+2]=(POS[i+2]-cz)/span}
const cv=document.getElementById('c'),gl=cv.getContext('webgl2',{antialias:true});
const sh=(t,s)=>{const x=gl.createShader(t);gl.shaderSource(x,s);gl.compileShader(x);
 if(!gl.getShaderParameter(x,gl.COMPILE_STATUS))throw gl.getShaderInfoLog(x);return x};
const pr=gl.createProgram();
gl.attachShader(pr,sh(gl.VERTEX_SHADER,`#version 300 es
in vec3 p;in vec3 c;uniform mat4 mvp;out vec3 w;out vec3 vc;
void main(){w=p;vc=c;gl_Position=mvp*vec4(p,1.0);}`));
gl.attachShader(pr,sh(gl.FRAGMENT_SHADER,`#version 300 es
precision highp float;in vec3 w;in vec3 vc;out vec4 o;
void main(){vec3 n=normalize(cross(dFdx(w),dFdy(w)));
 float l=0.40+0.60*abs(dot(n,normalize(vec3(0.4,0.85,0.3))));o=vec4(vc*l,1.0);}`));
gl.linkProgram(pr);gl.useProgram(pr);
const vb=gl.createBuffer();gl.bindBuffer(gl.ARRAY_BUFFER,vb);
gl.bufferData(gl.ARRAY_BUFFER,P,gl.STATIC_DRAW);
const ap=gl.getAttribLocation(pr,'p');gl.enableVertexAttribArray(ap);
gl.vertexAttribPointer(ap,3,gl.FLOAT,false,0,0);
const cb=gl.createBuffer();gl.bindBuffer(gl.ARRAY_BUFFER,cb);
gl.bufferData(gl.ARRAY_BUFFER,RGB,gl.STATIC_DRAW);
const ac=gl.getAttribLocation(pr,'c');gl.enableVertexAttribArray(ac);
gl.vertexAttribPointer(ac,3,gl.UNSIGNED_BYTE,true,0,0);
gl.enable(gl.DEPTH_TEST);gl.clearColor(0.051,0.063,0.075,1);
const uMVP=gl.getUniformLocation(pr,'mvp');
let yaw=-0.5,pitch=0.70,dist=1.25,tg=[0,0,0];
const mul=(a,b)=>{const o=new Float32Array(16);for(let i=0;i<4;i++)for(let j=0;j<4;j++){
 let s=0;for(let k=0;k<4;k++)s+=a[k*4+j]*b[i*4+k];o[i*4+j]=s}return o};
function basis(){const cp=Math.cos(pitch),sp=Math.sin(pitch);
 const d=[cp*Math.sin(yaw),sp,cp*Math.cos(yaw)];
 const eye=[tg[0]+dist*d[0],tg[1]+dist*d[1],tg[2]+dist*d[2]];
 const f=[-d[0],-d[1],-d[2]];let s=[-f[2],0,f[0]];
 const sl=Math.hypot(s[0],s[1],s[2])||1e-6;s=s.map(v=>v/sl);
 const u=[s[1]*f[2]-s[2]*f[1],s[2]*f[0]-s[0]*f[2],s[0]*f[1]-s[1]*f[0]];return{eye,f,s,u}}
function draw(){const dpr=Math.min(devicePixelRatio,2);
 cv.width=innerWidth*dpr;cv.height=innerHeight*dpr;gl.viewport(0,0,cv.width,cv.height);
 gl.clear(gl.COLOR_BUFFER_BIT|gl.DEPTH_BUFFER_BIT);
 const fv=1/Math.tan(0.42),a=cv.width/cv.height,n=0.002,fr=40;
 const proj=new Float32Array([fv/a,0,0,0,0,fv,0,0,0,0,(fr+n)/(n-fr),-1,0,0,2*fr*n/(n-fr),0]);
 const{eye,f,s,u}=basis(),dot=(p,q)=>p[0]*q[0]+p[1]*q[1]+p[2]*q[2];
 gl.uniformMatrix4fv(uMVP,false,mul(proj,new Float32Array(
  [s[0],u[0],-f[0],0,s[1],u[1],-f[1],0,s[2],u[2],-f[2],0,-dot(s,eye),-dot(u,eye),dot(f,eye),1])));
 gl.drawArrays(gl.TRIANGLES,0,P.length/3)}
let dg=false,sk=false,lx=0,ly=0;
cv.addEventListener('mousedown',e=>{dg=true;sk=e.shiftKey;lx=e.clientX;ly=e.clientY;cv.classList.add('drag')});
addEventListener('mouseup',()=>{dg=false;cv.classList.remove('drag')});
addEventListener('mousemove',e=>{if(!dg)return;const dx=e.clientX-lx,dy=e.clientY-ly;
 lx=e.clientX;ly=e.clientY;
 if(sk){const{s,u}=basis(),k=dist*0.0016;for(let i=0;i<3;i++)tg[i]+=(-s[i]*dx+u[i]*dy)*k}
 else{yaw-=dx*0.006;pitch=Math.max(-1.45,Math.min(1.45,pitch+dy*0.006))}draw()},{passive:true});
cv.addEventListener('wheel',e=>{e.preventDefault();
 dist=Math.max(0.004,Math.min(8,dist*Math.exp(e.deltaY*0.0016)));draw()},{passive:false});
addEventListener('resize',draw);
const V={vTop:[0,1.44,1.15],vPersp:[-0.5,0.70,1.25],vGround:[-0.5,0.05,0.09]};
for(const k in V)document.getElementById(k).onclick=()=>{[yaw,pitch,dist]=V[k];tg=[0,0,0];draw()};
const L=document.getElementById('list');
OBJS.forEach(o=>{const d=document.createElement('div');d.textContent=o.name;
 d.onclick=()=>{tg=[(o.p[0]-cx)/span,(o.p[1]-cy)/span,(o.p[2]-cz)/span];
  pitch=0.22;dist=(o.name==='OAKTREE'||o.name==='BRIDGE')?0.018:0.06;draw();
  d.style.color='var(--hi)';setTimeout(()=>d.style.color='',700)};L.appendChild(d)});
draw();</script></body></html>
"""

if __name__ == "__main__":
    n, o, sz = build(sys.argv[1], sys.argv[2])
    print("wrote %s: %d triangles, %d objects, %.2f MB" % (sys.argv[2], n, o, sz/1e6))
