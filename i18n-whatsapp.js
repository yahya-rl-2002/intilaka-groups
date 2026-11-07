const whatsappCopy={ar:'هل تحتاج إلى مساعدة؟',fr:"Besoin d'aide ?",en:'Need help?'};
const updateWhatsappCopy=()=>{const message=document.querySelector('.whatsapp-message');if(message)message.textContent=whatsappCopy[document.body.lang]||whatsappCopy.ar};
document.querySelectorAll('[data-language]').forEach(button=>button.addEventListener('click',()=>requestAnimationFrame(updateWhatsappCopy)));
updateWhatsappCopy();
