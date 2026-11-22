/* SVG display adapter for the shared broadcast scene. Canvas remains the recorder.
   Source text is XML-escaped. No account data or credentials are stored here. */
(() => {
  'use strict';
  const escape = value => String(value).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&apos;'}[c]));
  class BroadcastSVGContext {
    constructor(measurer) {
      this.measurer = measurer;
      this.commands = []; this.definitions = []; this.stack = []; this.path = ''; this.nextId = 0;
      this.state = {fillStyle:'#000', strokeStyle:'#000', lineWidth:1, font:'16px sans-serif', textAlign:'left', direction:'ltr', globalAlpha:1, transform:'', clip:'', dash:[]};
      for (const name of ['fillStyle','strokeStyle','lineWidth','font','textAlign','direction','globalAlpha']) {
        Object.defineProperty(this, name, {get:() => this.state[name], set:value => {this.state[name] = value;}});
      }
    }
    attrs() {
      return ` opacity="${this.state.globalAlpha}"${this.state.transform ? ` transform="${this.state.transform}"` : ''}${this.state.clip ? ` clip-path="url(#${this.state.clip})"` : ''}`;
    }
    paint(value) { return typeof value === 'object' ? `url(#${value.id})` : escape(value); }
    clearRect() { this.commands = []; }
    fillRect(x,y,w,h) { this.commands.push(`<rect x="${x}" y="${y}" width="${w}" height="${h}" fill="${this.paint(this.fillStyle)}"${this.attrs()}/>`); }
    beginPath() { this.path = ''; }
    moveTo(x,y) { this.path += `M ${x} ${y} `; }
    lineTo(x,y) { this.path += `L ${x} ${y} `; }
    rect(x,y,w,h) { this.path += `M ${x} ${y} h ${w} v ${h} h ${-w} Z `; }
    roundRect(x,y,w,h,r) {
      r = Math.min(Number(r),w/2,h/2);
      this.path += `M ${x+r} ${y} H ${x+w-r} Q ${x+w} ${y} ${x+w} ${y+r} V ${y+h-r} Q ${x+w} ${y+h} ${x+w-r} ${y+h} H ${x+r} Q ${x} ${y+h} ${x} ${y+h-r} V ${y+r} Q ${x} ${y} ${x+r} ${y} Z `;
    }
    arc(x,y,r) { this.path += `M ${x-r} ${y} A ${r} ${r} 0 1 0 ${x+r} ${y} A ${r} ${r} 0 1 0 ${x-r} ${y} Z `; }
    fill() { this.commands.push(`<path d="${this.path}" fill="${this.paint(this.fillStyle)}"${this.attrs()}/>`); }
    stroke() {
      this.commands.push(`<path d="${this.path}" fill="none" stroke="${this.paint(this.strokeStyle)}" stroke-width="${this.lineWidth}"${this.state.dash.length ? ` stroke-dasharray="${this.state.dash.join(' ')}"` : ''}${this.attrs()}/>`);
    }
    setLineDash(values) { this.state.dash = values.slice(); }
    save() { this.stack.push({...this.state,dash:this.state.dash.slice()}); }
    restore() { if (this.stack.length) this.state = this.stack.pop(); }
    translate(x,y) { this.state.transform += ` translate(${x} ${y})`; }
    rotate(radians) { this.state.transform += ` rotate(${radians*180/Math.PI})`; }
    clip() {
      const id = `broadcast-clip-${this.nextId++}`;
      this.definitions.push(`<clipPath id="${id}"><path d="${this.path}"/></clipPath>`); this.state.clip = id;
    }
    fillText(value,x,y) {
      let anchor = this.textAlign === 'center' ? 'middle' : this.textAlign === 'right' ? 'end' : 'start';
      if (this.direction === 'rtl' && anchor !== 'middle') anchor = anchor === 'start' ? 'end' : 'start';
      const ticker = String(value).includes('     /     ');
      const label = `<text x="${x}" y="${y}" text-anchor="${anchor}" direction="${this.direction}" style="font:${escape(this.font)};unicode-bidi:plaintext" fill="${this.paint(this.fillStyle)}"${ticker ? '' : this.attrs()}>${escape(value)}</text>`;
      if (ticker) {
        const distance = this.measureText(String(value)).width + 100;
        this.commands.push(`<g${this.attrs()}><g><animateTransform attributeName="transform" type="translate" from="0 0" to="${-distance} 0" dur="${distance/35}s" repeatCount="indefinite"/>${label}</g></g>`);
      } else this.commands.push(label);
    }
    measureText(value) {
      this.measurer.save(); this.measurer.font = this.font;
      const result = this.measurer.measureText(String(value)); this.measurer.restore(); return result;
    }
    drawImage(img,x,y,w,h) { this.commands.push(`<image href="${escape(img.src)}" x="${x}" y="${y}" width="${w}" height="${h}"${this.attrs()}/>`); }
    createRadialGradient(fx,fy,inner,cx,cy,r) {
      const gradient = {id:`broadcast-gradient-${this.nextId++}`,stops:[],addColorStop(offset,color){this.stops.push([offset,color]);}};
      this.definitions.push(() => `<radialGradient id="${gradient.id}" gradientUnits="userSpaceOnUse" cx="${cx}" cy="${cy}" r="${r}" fx="${fx}" fy="${fy}">${gradient.stops.map(([offset,color])=>`<stop offset="${offset}" stop-color="${escape(color)}"/>`).join('')}</radialGradient>`);
      return gradient;
    }
    markup() {
      return `<defs>${this.definitions.map(d=>typeof d==='function'?d():d).join('')}</defs>${this.commands.join('')}`;
    }
  }
  window.AvinaSVGContext = BroadcastSVGContext;
})();
