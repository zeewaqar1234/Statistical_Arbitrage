import fs from 'node:fs/promises';
import {FileBlob, PresentationFile} from '@oai/artifact-tool';
const root='/Users/syedzeewaqarhussain/crypto_hft_tool/reports/tool_briefing';
const deck=await PresentationFile.importPptx(await FileBlob.load(root+'/output/Crypto_Arbitrage_Senior_Briefing.pptx'));
await fs.mkdir(root+'/.build/final_slides',{recursive:true});
for(let i=0;i<deck.slides.items.length;i++){
 const blob=await deck.export({slide:deck.slides.items[i],format:'png',scale:1});
 await fs.writeFile(root+'/.build/final_slides/slide-'+String(i+1).padStart(2,'0')+'.png',new Uint8Array(await blob.arrayBuffer()));
}
console.log('Rendered all '+deck.slides.items.length+' final slides.');
