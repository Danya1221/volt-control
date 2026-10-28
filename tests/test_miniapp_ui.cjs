const fs=require('fs'),vm=require('vm'),assert=require('assert');
class Element{
 constructor(tag){this.tag=tag;this.children=[];this.attributes={};this.dataset={};this.hidden=false;this.value='';this.textContent='';this.style={}}
 append(...children){this.children.push(...children)}
 replaceChildren(...children){this.children=[...children]}
 setAttribute(k,v){this.attributes[k]=v}
}
const ids=['accounts','error','metrics','catalog','pricing','pricingRules','reviews','reviewsBtn','pricingBtn','catalogBtn','reload',...['home','catalog','pricing','suppliers','reviews','preview'].map(s=>'tab-'+s)];
const elements=Object.fromEntries(ids.map(id=>[id,new Element('div')]));
const buttons=['home','catalog','pricing','suppliers','reviews','preview'].map(x=>{let e=new Element('button');e.dataset.tab=x;return e});
const shortcuts=['reviews','suppliers','catalog'].map(x=>{let e=new Element('button');e.dataset.go=x;return e});
const doc={getElementById:id=>elements[id],createElement:tag=>new Element(tag),querySelectorAll:q=>q==='[data-tab]'?buttons:shortcuts};
const p={id:1,model:'Example',category:'Example',approved:true,hidden:false,price:'70',status:'priced',sim:''};
const data={'/accounts':[{connected:true}],'/products':[p],'/markups':[],'/pricing/overview':{total:1,priced:1,review:0,items:[{id:1,price:'90',status:'priced'}]}};
const code=fs.readFileSync('app/static/miniapp.html','utf8').split('<script>').pop().split('</script>')[0];
const context={document:doc,window:{Telegram:{WebApp:{initData:'test',ready(){},expand(){}}}},fetch:async url=>{let key=url.replace('/miniapp/api','');if(!(key in data))throw Error('Unexpected '+key);return {ok:true,json:async()=>data[key]}},console,setTimeout,clearTimeout,confirm:()=>false,Date,Map,encodeURIComponent};
vm.createContext(context);vm.runInContext(code,context);
const all=e=>String(e.textContent)+' '+e.children.map(all).join(' ');
(async()=>{await new Promise(r=>setImmediate(r));assert.equal(elements['tab-home'].hidden,false);assert.equal(elements['tab-catalog'].hidden,true);assert.match(all(elements.metrics),/Товаров  *1/);await vm.runInContext('loadCatalog()',context);let txt=all(elements.catalog);assert.match(txt,/Расчётная цена: 90/);assert.doesNotMatch(txt,/Расчётная цена: 70/);vm.runInContext("showTab('preview')",context);assert.equal(elements['tab-preview'].hidden,false);assert.equal(elements['tab-home'].hidden,true);console.log('UI navigation and authoritative price passed');})().catch(e=>{console.error(e);process.exit(1)});
