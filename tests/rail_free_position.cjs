const fs = require("node:fs");
const vm = require("node:vm");
const assert = require("node:assert/strict");
const html = fs.readFileSync("components/chart_draw/index.html", "utf8");
const source = "function positionRightControlRail()" +
  html.split("function positionRightControlRail()")[1].split("\nfunction fitRailContent()")[0];
const toolbar = {style:{height:"600px"}, offsetWidth:280, offsetHeight:600};
const tab = {style:{}};
const context = {
  toolbarEl:toolbar, railDock:"free", railFreeTop:100, railFreeLeft:400,
  railTopOffset:0, railManuallySized:true, railCollapsed:false,
  fitRailContent(){}, positionRailResizeHandles(){},
  visibleRailBounds:()=>({top:12,bottom:1200}),
  document:{
    documentElement:{clientWidth:1200},
    getElementById:id => id === "inclination-bar" ?
      {offsetTop:400,offsetHeight:80} : tab
  }
};
vm.createContext(context);
vm.runInContext(source, context);
const position = () => vm.runInContext("positionRightControlRail()", context);
position();
assert.equal(toolbar.style.top, "100px", "Free panel can move 392px above the old plot boundary");
assert.equal(toolbar.style.left, "400px");
context.railFreeTop = -200;
position();
assert.equal(toolbar.style.top, "12px", "Header remains inside the visible page");
context.railFreeTop = 1100;
position();
assert.equal(toolbar.style.top, "600px", "Bottom controls remain reachable");
context.railDock = "right";
position();
assert.equal(toolbar.style.top, "504px", "Default docking still leaves the incline bar unobstructed");
assert.equal(toolbar.style.right, "12px");
console.log("Free console positioning passed: above-chart movement, reachable header and bottom, preserved default dock.");
