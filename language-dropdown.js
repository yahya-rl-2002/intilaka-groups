const languageDropdown=document.querySelector('.language-dropdown');
const languageTrigger=document.querySelector('.language-trigger');
const languageNames={ar:'العربية',fr:'Français',en:'English'};
function syncLanguageDropdown(){const lang=document.body.lang||'ar';document.querySelector('.current-language').textContent=languageNames[lang];document.querySelectorAll('.language-dropdown-menu [data-language]').forEach(button=>button.classList.toggle('active',button.dataset.language===lang))}
languageTrigger.addEventListener('click',event=>{event.stopPropagation();const open=languageDropdown.classList.toggle('open');languageTrigger.setAttribute('aria-expanded',String(open))});
document.querySelectorAll('.language-dropdown-menu [data-language]').forEach(button=>button.addEventListener('click',()=>{languageDropdown.classList.remove('open');languageTrigger.setAttribute('aria-expanded','false');requestAnimationFrame(syncLanguageDropdown)}));
document.addEventListener('click',event=>{if(!languageDropdown.contains(event.target)){languageDropdown.classList.remove('open');languageTrigger.setAttribute('aria-expanded','false')}});document.addEventListener('keydown',event=>{if(event.key==='Escape'){languageDropdown.classList.remove('open');languageTrigger.setAttribute('aria-expanded','false')}});syncLanguageDropdown();
