# 这次演示实际验证过的经验（2026-10-07）

官方接口：https://frida.re/docs/javascript-api/ 。版本变化时重新核对。

## Bridge 与日志

Frida 17的原始create_script不一定含Java全局。本机用已安装frida_tools/bridges/java.js，其导出是bridge，赋globalThis.Java=bridge，再50ms后Script.evaluate用户脚本。检查实际bridge文件而非猜导出名，不输出整份压缩源码。

公开验证用import frida、get_usb_device、enumerate_processes/目标enumerate_applications。别因顶层import _frida失败认定公开客户端不可用。本机Script只有exports_sync，没有exports_async；读实际客户端再选调用方式。exports_sync等待要有外层有界机制，并确保超时释放脚本。

console.log通过Script.set_log_handler(level,text)，不是message回调的console分支。检查器必须真正接收日志才能判断HOOK_READY。

## 目标界面与类型

本例包com.redqueen.fridaflowerdemo，MainActivity，按钮id2130771969。目标按钮performClick返回true，却没有调用onLoginSuccess，因此只hook该方法不会实现按钮效果。这是本例证据，不能泛化到所有App。

MIUI该构建的ActivityThread.mCurrentActivity是String，不是Activity；Java.choose目标MainActivity后retain，在Java.scheduleOnMainThread操作视图。findViewById泛型结果在该bridge里必须cast View，再调用其方法。容器cast ViewGroup/FrameLayout；接口对象要打印getClass可先cast Object。

setOnClickListener要求Java OnClickListener实例；用Java.registerClass({name,implements:[Java.use('android.view.View$OnClickListener')],methods:{onClick}})并$new，不能传JS普通对象。View.mListenerInfo.value内部的mOnClickListener.value或反射获取才是原监听，直接读View.mOnClickListener得到null/undefined不说明没有监听。

Java enum/静态数值字段取.value；int数组Java.array('int',[0,0])；颜色用signed int。这个bridge的CharSequence参数需要Java String实例，裸JS字符串会导致setText/setHint/setTitle重载错误。保存/替换前的原监听，恢复后明确确认。

## 故障诊断

本例Vector对目标App启用fakepers的作用域造成Frida Java初始化ART abort，日志method_index/num_methods mismatch。这里只曾按用户授权隔离目标包作用域并保留恢复记录，其他App/全局模块未改。不要遇到任何Java失败就禁用模块；先取目标PID的有界crash日志，明确证据后再决定是否需要获准的局部调整。

## 验收

启动器可停止持续存活，真实root触屏点击触发黑花，1000ms定时器后弹窗，实测1170/1165ms；停止后LISTENER_RESTORED与RESTORE_CONFIRMED true，退出0。截图只证明当时画面，不证明长期运行。探测结束要清理；交付时确保持续实例实际启动且不重复。

## 无障碍树与截图点击

用户要求操作界面时，优先使用无障碍树而非猜坐标或只在内存里直接调用回调。

- 先核对目标包处于前台、设备序列号是用户授权目标；遇到锁屏、遮挡或系统弹窗时，先确认当前状态，再按用户本次要求处理并重新定位。
- 使用ADB调用uiautomator dump，取得当前界面的XML；根据当前任务定位相关包和节点。匹配resource-id、content-desc、控件文字、class、clickable/enabled和bounds，出现多个候选时结合父子层级明确唯一目标。
- 输入框与跨应用节点是否需要处理，按用户本次任务确定。界面树里缺失的自绘控件再用截图定位，不能凭历史画面推断当前按钮位置。
- 用ADB exec-out screencap -p取得当前PNG，查看画面核对目标、遮挡和点击坐标。树的bounds属于屏幕坐标，选择范围内中心点；每次布局、弹窗或焦点变化后刷新树和截图。
- 在已经确认的节点上通过可用的无障碍点击接口执行；仅有ADB时可将最新树节点bounds转换为input tap坐标。这是依据树定位的触屏点击，不是Frida performClick替代验收。需要root的既有授权环境，用正确引用的su -c完整命令，记录返回码和stderr。
- 点击后重新取目标树/截图，并检查用户要求的状态变化或真实回调事件；input tap返回0不证明按钮生效。树、截图、触发日志不一致时记录失败并定位原因。
- 主线程View.performClick只作为区分“触屏未命中”和“业务回调未执行”的受控诊断。交付验收优先再次从真实界面点击，不能把RPC点击成功说成触屏成功。
