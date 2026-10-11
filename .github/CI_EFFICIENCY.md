# Uso eficiente de GitHub Actions

Política aprobada el 11-10-2026 para toda la cuenta `zirbio`. La cuota y el
presupuesto de Actions se comparten entre sus repositorios privados.

- El CI habitual comprueba PR y el commit integrado en la rama principal.
- Cancelar sólo verificaciones obsoletas; despliegues y tareas operativas se conservan.
- Los componentes seleccionados ejecutan sus controles completos. Una ruta desconocida,
  una configuración compartida o un diff no fiable activan la comprobación amplia.
- Documentación humana puede omitir pruebas de producto; skills, prompts y plantillas
  ejecutables siempre se verifican. El agregador rechaza fallos y omisiones inesperadas.
- Mantener hooks, cobertura, controles de privacidad, permisos, migraciones y recuperación.
- Las pruebas profundas/manuales se invocan por riesgo o publicación; no como cierre
  automático de cada microcambio. Un CI habitual verde no acredita una release profunda.
- Medir uso real en Billing durante un ciclo representativo antes de afirmar ahorro.
  Un presupuesto mensual no es una compra anticipada ni obliga a consumirlo.

Los repositorios públicos con runners estándar no consumen la cuota privada.
No se han añadido crons de suites completas ni cambiado servicios de producción.
