(function () {
    console.log("HOOK_SCRIPT_START");
    if (typeof Java === "undefined" || !Java.available) {
        console.log("HOOK_ERROR: Java bridge unavailable");
        return;
    }

    function text(value){return Java.use('java.lang.String').$new(value);}
    var MAIN_ACTIVITY = "com.redqueen.fridaflowerdemo.MainActivity";
    var LOGIN_BTN_ID = 2130771969;
    var FIRED = false;
    var flowerView = null;
    var sessionActivity = null;
    var loginBtnRef = null;
    var origListener = null;
    var activeDialog=null;
    var dialogTimer=null;

    function currentActivity(){return sessionActivity;}
    rpc.exports={clickdemo:function(){
        return new Promise(function(resolve,reject){
            Java.perform(function(){Java.scheduleOnMainThread(function(){
                try{if(!loginBtnRef)throw new Error('not ready');resolve(loginBtnRef.performClick());}
                catch(e){reject(String(e));}
            });});
        });
    },restore:function(){
        return new Promise(function(resolve,reject){
            Java.perform(function(){Java.scheduleOnMainThread(function(){
                try{
                    if(dialogTimer!==null)clearTimeout(dialogTimer);
                    if(loginBtnRef)loginBtnRef.setOnClickListener.overload('android.view.View$OnClickListener').call(loginBtnRef,origListener);
                    if(activeDialog)activeDialog.dismiss();
                    if(flowerView && sessionActivity)Java.cast(sessionActivity.getWindow().getDecorView(),Java.use('android.view.ViewGroup')).removeView(flowerView);
                    console.log('LISTENER_RESTORED');resolve(true);
                }catch(e){reject(String(e));}
            });});
        });
    }};

    function chainHas(v, name) {
        var c;
        try { c = v.getClass(); } catch (e) { return false; }
        while (c !== null) {
            try {
                if (c.getName().toString() === name) return true;
            } catch (e) { return false; }
            c = c.getSuperclass();
        }
        return false;
    }

    function findViewById(root, id, depth) {
        if (!root || depth > 40) return null;
        try {
            if (root.getId() === id) return root;
        } catch (e) {}
        if (chainHas(root, "android.view.ViewGroup")) {
            var n = 0;
            try { n = root.getChildCount(); } catch (e) {}
            for (var i = 0; i < n; i++) {
                var r;
                try { r = root.getChildAt(i); } catch (e) { r = null; }
                var hit = findViewById(r, id, depth + 1);
                if (hit) return hit;
            }
        }
        return null;
    }

    function findActivity(v) {
        var cur = v;
        for (var i = 0; i < 50 && cur; i++) {
            try {
                var cls = Java.use("android.app.Activity").class;
                if (cls.isAssignableFrom(cur.getClass())) return cur;
            } catch (e) {}
            var next = null;
            try { next = cur.getParent(); } catch (e) { next = null; }
            if (!next) break;
            cur = next;
        }
        return null;
    }

    function drawBlackFlowerBitmap(px) {
        var Bitmap = Java.use("android.graphics.Bitmap");
        var Config = Java.use("android.graphics.Bitmap$Config");
        var Canvas = Java.use("android.graphics.Canvas");
        var Paint = Java.use("android.graphics.Paint");
        var Style = Java.use("android.graphics.Paint$Style");
        var RectF = Java.use("android.graphics.RectF");
        var bmp = Bitmap.createBitmap(px, px, Config.ARGB_8888.value);
        var c = Canvas.$new(bmp);
        var fill = Paint.$new();
        fill.setAntiAlias(true);
        fill.setStyle(Style.FILL.value);
        fill.setColor(-16777216);
        var stroke = Paint.$new();
        stroke.setAntiAlias(true);
        stroke.setStyle(Style.STROKE.value);
        stroke.setStrokeWidth(3);
        stroke.setColor(-1);
        var cx = px / 2;
        var rect = RectF.$new(px * 0.38, px * 0.10, px * 0.62, px * 0.44);
        for (var i = 0; i < 6; i++) {
            c.save();
            c.rotate(i * 60, cx, cx);
            c.drawOval(rect, fill);
            c.drawOval(rect, stroke);
            c.restore();
        }
        c.drawCircle(cx, cx, px * 0.13, fill);
        c.drawCircle(cx, cx, px * 0.13, stroke);
        return bmp;
    }

    function showBlackFlower(activity) {
        var FrameLayout = Java.use("android.widget.FrameLayout");
        var ImageView = Java.use("android.widget.ImageView");
        var TextView = Java.use("android.widget.TextView");
        var Lp = Java.use("android.widget.FrameLayout$LayoutParams");
        var Gravity = Java.use("android.view.Gravity");
        var decor = Java.cast(activity.getWindow().getDecorView(),FrameLayout);
        var px = 260;

        var bmp = drawBlackFlowerBitmap(px);
        var fl = FrameLayout.$new(activity);
        var iv = ImageView.$new(activity);
        iv.setImageBitmap(bmp);
        var ivlp = Lp.$new(px, px);
        fl.addView(iv, ivlp);
        var tv = TextView.$new(activity);
        tv.setText(text('黑花'));
        tv.setTextColor(-16777216);
        var tvlp = Lp.$new(-2, -2, (Gravity.CENTER_HORIZONTAL.value | Gravity.BOTTOM.value));
        fl.addView(tv, tvlp);

        if (flowerView !== null) {
            try { decor.removeView(flowerView); } catch (e) {}
        }
        var flp = Lp.$new(px, px + 56, Gravity.CENTER.value);
        decor.addView(fl, flp);
        flowerView = fl;
        console.log("FLOWER_ADDED timestamp_ms="+Date.now()+" px="+px);
    }

    function showLoginDialog(activity) {
        var Builder = Java.use("android.app.AlertDialog$Builder");
        var EditText = Java.use("android.widget.EditText");
        var LinearLayout = Java.use("android.widget.LinearLayout");
        var Lp = Java.use("android.widget.LinearLayout$LayoutParams");

        var ll = LinearLayout.$new(activity);
        ll.setOrientation(1);
        var et1 = EditText.$new(activity);
        et1.setHint(text('账号'));
        et1.setInputType(1);
        ll.addView(et1, Lp.$new(-1, -2));
        var et2 = EditText.$new(activity);
        et2.setHint(text('密码'));
        et2.setInputType(1 | 128);
        ll.addView(et2, Lp.$new(-1, -2));

        var b = Builder.$new(activity);
        b.setTitle(text('输入账号密码'));
        b.setView(ll);
        b.setPositiveButton(text('确定'), null);
        b.setNegativeButton(text('取消'), null);
        activeDialog=Java.retain(b.show());
        console.log("DIALOG_SHOWN timestamp_ms="+Date.now());
        FIRED=false;
    }

    function fire(activity) {
        if (FIRED) {
            console.log("HOOK: already fired, skip");
            return;
        }
        FIRED = true;
        try {
            showBlackFlower(activity);
            var retained=Java.retain(activity);
            dialogTimer=setTimeout(function () {
                Java.scheduleOnMainThread(function () {
                    try{showLoginDialog(retained);}
                    catch(e){console.log('HOOK_ERROR: '+e+'\n'+(e.stack||''));}
                    finally{retained.$dispose();}
                });
            },1000);
            console.log("DIALOG_SCHEDULED delay_ms=1000");
        } catch (e) {
            FIRED=false;
            console.log("HOOK_ERROR: " + e);
        }
    }

    Java.perform(function () {
        var MainActivity = Java.use(MAIN_ACTIVITY);
        MainActivity.onLoginSuccess.overloads.forEach(function (ov) {
            ov.implementation = function () {
                console.log("HOOK: onLoginSuccess intercepted (original skipped)");
                fire(this);
            };
        });
        console.log("ONLOGIN_HOOK_INSTALLED");

        Java.choose(MAIN_ACTIVITY, {
            onMatch: function(instance) {
                var activity=Java.retain(instance);
                Java.scheduleOnMainThread(function(){
                    try {
                        console.log('READY_STAGE get_decor');
                        var View=Java.use('android.view.View');
                        var decor=activity.getWindow().getDecorView();
                        console.log('READY_STAGE find_button');
                        var btn=View.findViewById.overload('int').call(decor,LOGIN_BTN_ID);
                        if(btn)btn=Java.cast(btn,View);
                        if(!btn) throw new Error('login button not found');
                        var loc=Java.array('int',[0,0]);
                        btn.getLocationOnScreen(loc);
                        console.log('BTN_LOC=('+(loc[0]+btn.getWidth()/2)+','+(loc[1]+btn.getHeight()/2)+')');
                        sessionActivity=activity;
                        loginBtnRef=Java.retain(btn);
                        var field=View.class.getDeclaredField('mListenerInfo');
                        field.setAccessible(true);
                        var info=field.get(btn);
                        if(info){
                            var listenerInfo=Java.cast(info,Java.use('android.view.View$ListenerInfo'));
                            var original=listenerInfo.mOnClickListener.value;
                            origListener=original?Java.retain(original):null;
                        }
                        console.log('ORIG_LISTENER='+(origListener?Java.cast(origListener,Java.use('java.lang.Object')).getClass().getName():'null'));
                        var Listener=Java.registerClass({
                            name:'com.redqueen.fridaflowerdemo.MonitorDemoClick'+Date.now(),
                            implements:[Java.use('android.view.View$OnClickListener')],
                            methods:{onClick:function(v){
                                console.log('HOOK: demo listener onClick');
                                fire(sessionActivity);
                            }}
                        });
                        btn.setOnClickListener.overload('android.view.View$OnClickListener').call(btn,Listener.$new());
                        console.log('DEMO_LISTENER_INSTALLED');
                        console.log('HOOK_READY');
                    } catch(e){console.log('HOOK_ERROR: '+e+'\n'+(e.stack||''));}
                });
                return 'stop';
            },
            onComplete:function(){}
        });
    });

})();
