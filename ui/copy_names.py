"""Compact comma-separated names with browser-side clipboard controls."""
import streamlit as st

from dataforge.exports import COPY_JS

_COPY_NAMES = st.components.v2.component(
    "gravetrail_copy_names",
    html='<div class="names"><button class="copy-list" type="button">Copy list</button><span class="status" role="status"></span><div class="list"></div></div>',
    css="""
    .names{font:14px/1.8 var(--st-font,system-ui);color:var(--st-text-color)}
    button{font:inherit;cursor:pointer;color:inherit;background:var(--st-secondary-background-color);border:1px solid var(--st-border-color);border-radius:6px;padding:3px 9px}
    button:focus-visible{outline:2px solid var(--st-primary-color);outline-offset:2px}
    .list{margin-top:8px;max-height:240px;overflow:auto;overflow-wrap:anywhere}
    .item{display:inline-flex;align-items:baseline;gap:4px;margin-right:5px}
    .item button{padding:0 5px;background:transparent;border-color:transparent}
    .status{margin-left:10px;font-size:12px}
    """,
    js=COPY_JS + """
    export default function(c){
      const root=c.parentElement,list=root.querySelector('.list'),status=root.querySelector('.status');
      list.replaceChildren();
      const copy=async text=>{status.textContent=await copyText(text)?'Copied':'Copy failed. Select the text and copy manually.'};
      root.querySelector('.copy-list').onclick=()=>copy(c.data.names.join(', '));
      c.data.names.forEach((name,i)=>{
        const item=document.createElement('span');item.className='item';
        const label=document.createElement('code');label.textContent=name;item.append(label);
        const button=document.createElement('button');button.type='button';button.textContent='⧉';
        button.setAttribute('aria-label','Copy '+name);button.title='Copy '+name;button.onclick=()=>copy(name);item.append(button);
        if(i<c.data.names.length-1)item.append(document.createTextNode(','));
        list.append(item);
      });
    }
    """,
)


def copy_names(names: list[str], key: str) -> None:
    """Render the copy-names component for a list of asset names.

    Args:
        names: Names presented by the component.
        key: Unique Streamlit component key.
    """
    _COPY_NAMES(data={"names": names}, key=key, height="content")
